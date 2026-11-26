# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Sealed build123d kernel adapter (Phase 0, T2).

This module is the only product-code location allowed to import ``build123d``
(enforced by ``tests/test_layering.py``). No build123d/OCP/numpy object ever
leaves the ``mycad.geom`` package through the neutral DTOs it returns.

Conventions (project-wide): lengths are millimetres, angles are decimal
degrees. ``feature.cylinder`` primitives are centered on ``center`` with the
axis along +Z spanning z in [-height/2, +height/2]. Boolean modes are the
strings ``new`` / ``add`` / ``cut`` mapped to build123d ``Mode.NEW`` /
``Mode.ADD`` / ``Mode.SUBTRACT``.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Literal, Protocol, cast

import build123d
from build123d import CenterOf, Edge, Face, GeomType, Part, PositionMode

from mycad.core.associative_array import (
    ArrayBasePoint,
    ArrayEntityRef,
    ArrayExtraOutput,
    ArrayReplacement,
    AssociativeRectArray,
    erase_array_members,
    erase_drawing_entities,
    has_interleaved_array_dependencies,
    has_internal_replacements,
    move_associative_array,
    move_associative_array_with_offsets,
    predict_chain_reorder,
    propagate_array_changes,
    replace_and_erase_array_members,
    replace_array_cell_with_extra_outputs,
    reset_array_member_overrides,
    resize_array,
    set_array_member_offsets,
    set_array_member_replacements,
    set_array_member_rotations,
    set_array_offsets_batch,
    set_array_rotations_batch,
    strip_erased_member_dimensions,
    update_array_spacing,
    validate_array_cross_changes,
)
from mycad.core.bound_refs import BoundFaceRef, is_bound_hole
from mycad.core.command_identity import ExecutionContext
from mycad.core.cross_sketch_tangency import (
    CrossSketchTangency,
    RectangleTransformEvidence,
    build_tangency_revisions,
    closed_polyline_vertex_rotation_index,
    has_rectangle_segment_tangency,
    is_inferred_reference_rebind,
    is_unchanged_inferred_polyline_reference_rebind,
    is_unchanged_user_polyline_reference_rebind,
    rebind_committed_tangencies,
    rebind_committed_tangencies_for_edit,
    rebind_rectangle_constraints_for_sketch,
    rebind_retained_local_tangencies,
    rectangle_transform_kind_change_allowed,
    relations_use_rectangle_segments,
    resolve_tangency_component,
    tangent_entity_curve,
    unique_containing_polyline_arc,
    unique_extended_polyline_segment,
    unique_retained_relation_arc,
    unique_retained_relation_fragment,
    unique_retained_relation_line,
    unique_split_arc_relation_fragment,
    unique_split_line_relation_fragment,
    unique_unchanged_polyline_segment,
    validate_tangency_component,
)
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.dimension_translation import is_rigid_dimension_translation
from mycad.core.document_references import DocumentReference
from mycad.core.drawing import DrawingState
from mycad.core.drawing_blocks import (
    BlockDefinition,
    BlockInstance,
    expand_block,
    validate_block_definition_edit,
    validate_block_instance,
)
from mycad.core.drawing_codec import apply_drawing_command
from mycad.core.drawing_collection_state import BlockLibraryOrigin, DrawingCollectionState
from mycad.core.drawing_detail import clip_detail_projection
from mycad.core.drawing_groups import DrawingGroup, DrawingGroupTable, DrawingObjectRef
from mycad.core.drawing_object_refs import DrawingObjectCatalog, validate_group_members
from mycad.core.drawing_projection import (
    DrawingProjectionRequest,
    DrawingSourceSnapshot,
    ProjectionResult,
    ViewBasis,
)
from mycad.core.drawing_quick_regions import SampledMeasuredRegion
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyleTable, text_style_geometry_signature
from mycad.core.exceptions import (
    GeometryBuildError,
    GeomVersionError,
    MycadError,
    TopologyReferenceError,
    ValidationError,
)
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumAttachment,
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    SurfaceIndication,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_geometry import (
    box_aware_leader_is_safe,
    relocate_automatic_leader,
    reroute_leader_around_box,
    reroute_orthogonal_leader,
)
from mycad.core.geometric_tolerance_topology import (
    CurvePointIdentities,
    PolylineTopologyMap,
    apply_curve_identity_upgrade,
    associative_topology_entities,
    has_internal_reorder_dependents,
    new_curve_point_identities,
    rebind_array_base,
    rebind_proven_array_tangencies,
    remap_annotations,
    simple_array_reorder_chain,
    simple_array_reorder_members,
    stable_array_base_ids,
    validate_curve_identity_preservation,
    validate_topology_constraint_rebinding,
)
from mycad.core.geometry_checks import GeometryCheckResult
from mycad.core.geometry_types import MassProperties, Tessellation
from mycad.core.identity import BodyId, FeatureId, RuntimeIdentityScope, TopologyId
from mycad.core.measurements import (
    MeasurementKind,
    MeasurementRequest,
    MeasurementResult,
    MeasurementTarget,
)
from mycad.core.polyline_curves import polyline_curve_segments, polyline_sampled_points
from mycad.core.selectors import AxisLiteral, EdgeSelector, FaceSelector
from mycad.core.semantic_refs import (
    EdgePredicate,
    FacePredicate,
    SemanticEdgeRef,
    SemanticFaceRef,
    TopologyResolutionEvidence,
)
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
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
    DIMENSION_KINDS,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
    is_reference_value_refresh,
)
from mycad.core.sketch_layers import SketchLayerTable, merge_layer_tables
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_references import SpatialReference
from mycad.core.topology_evolution import TopologyEvolution
from mycad.core.viewport_protocol import (
    PlanarFaceFrame,
    ViewportBodyOrigin,
    ViewportBoundaryEdge,
    ViewportData,
    ViewportDatum,
    ViewportFace,
    ViewportSketchCurve,
    ViewportSketchData,
    ViewportSketchDimension,
    ViewportSketchPoint,
    ViewportSketchRegion,
    ViewportSnapAnchor,
    ViewportVertex,
)
from mycad.geom._b123_features import (
    apply_bound_hole,
    apply_feature,
    apply_sketch_extrusion,
    apply_sketch_hole,
    apply_sketch_revolve,
)
from mycad.geom._b123_ops import apply_primitive, checked_mapping
from mycad.geom.body_provenance import BodyOrigin, operation_origins
from mycad.geom.design_faces import DesignFaces
from mycad.geom.drawing_detail import clip_detail_exact
from mycad.geom.drawing_projection import project_shape
from mycad.geom.drawing_section import project_section
from mycad.geom.io import write_step, write_stl
from mycad.geom.query import (
    build_boundary_edges,
    build_mass_properties,
    build_tessellation,
    build_viewport_topology,
    measure_circular_edge_center_distance,
    measure_cylindrical_face_diameter,
    measure_parallel_plane_separation,
    normalize_tessellation_tolerances,
    require_valid_result,
    validate_result,
)
from mycad.geom.selectors import (
    bind_semantic_edge as bind_semantic_edge_ref,
)
from mycad.geom.selectors import (
    bind_semantic_face as bind_semantic_face_ref,
)
from mycad.geom.selectors import (
    body_selector_for_index,
    ordered_face_candidates,
    resolve_edges,
    resolve_face,
)
from mycad.geom.selectors import (
    resolve_semantic_edge as resolve_semantic_edge_ref,
)
from mycad.geom.selectors import (
    resolve_semantic_face as resolve_semantic_face_ref,
)
from mycad.geom.spatial_datums import associated_frame, evaluate_datum

EXPECTED_B123D_VERSION: tuple[int, int, int] = (0, 11, 1)
EXPECTED_B123D_VERSION_STR = ".".join(str(part) for part in EXPECTED_B123D_VERSION)


def _parse_version_tuple(raw: str) -> tuple[int, int, int]:
    """Parse ``major.minor.micro`` into an int triple; anything else fails."""

    segments = raw.split(".")
    if len(segments) != 3:
        msg = (
            f"build123d version {raw!r} is not parseable as 'major.minor.micro' "
            f"integers; expected {EXPECTED_B123D_VERSION_STR}"
        )
        raise GeomVersionError(message=msg)
    try:
        parsed = tuple(int(segment) for segment in segments)
    except ValueError:
        msg = (
            f"build123d version {raw!r} is not parseable as 'major.minor.micro' "
            f"integers; expected {EXPECTED_B123D_VERSION_STR}"
        )
        raise GeomVersionError(message=msg) from None
    return (parsed[0], parsed[1], parsed[2])


def assert_b123d_version(raw: str | None = None) -> None:
    """Assert the installed build123d matches the pinned version.

    The version is read from ``importlib.metadata.version("build123d")`` —
    the unique version source (``build123d.__version__`` is deliberately
    never read so the gate cannot be bypassed by patching it).
    """

    actual_raw = raw if raw is not None else importlib.metadata.version("build123d")
    actual = _parse_version_tuple(actual_raw)
    if actual != EXPECTED_B123D_VERSION:
        msg = (
            f"build123d version mismatch: actual {actual_raw!r} "
            f"(parsed {actual}), expected {EXPECTED_B123D_VERSION_STR} "
            f"(parsed {EXPECTED_B123D_VERSION})"
        )
        raise GeomVersionError(message=msg)


assert_b123d_version()


# Default mesh extraction tolerances for the viewport port (plan todo 3).
# Linear = chordal deviation (mm), angular = angular deviation (decimal
# degrees). Sized for the phase-1 GUI preview scale (OD80-class parts);
# explicit arguments to ``viewport_data`` always take precedence.
DEFAULT_MESH_LINEAR_TOLERANCE_MM: float = 0.1
DEFAULT_MESH_ANGULAR_TOLERANCE_DEG: float = 15.0
CURRENT_MESH_CACHE_MAX_ENTRIES: int = 4
HISTORY_MESH_CACHE_MAX_ENTRIES: int = 16

CurrentMeshCacheKey = tuple[int, int, float, float]
HistoryMeshCacheKey = tuple[int, int, str, float, float]
ViewportTopology = tuple[
    tuple[ViewportFace, ...],
    tuple[ViewportVertex, ...],
    tuple[TopologyId, ...],
    tuple[BodyId, ...],
]


def _axis_literal(vector: tuple[float, float, float]) -> AxisLiteral | None:
    """Return a global signed axis only for an axis-aligned normal."""

    axes: tuple[tuple[tuple[float, float, float], AxisLiteral], ...] = (
        ((1.0, 0.0, 0.0), "+X"),
        ((-1.0, 0.0, 0.0), "-X"),
        ((0.0, 1.0, 0.0), "+Y"),
        ((0.0, -1.0, 0.0), "-Y"),
        ((0.0, 0.0, 1.0), "+Z"),
        ((0.0, 0.0, -1.0), "-Z"),
    )
    for axis, name in axes:
        dot = sum(actual * expected for actual, expected in zip(vector, axis, strict=True))
        if dot > 1.0 - 1e-9:
            return name
    return None


class _SphereFace(Protocol):
    def geom_adaptor(self) -> object: ...


def _sphere_value(obj: object, name: str) -> object:
    return cast("Callable[[], object]", getattr(obj, name))()


@dataclass(frozen=True)
class RecordedOperation:
    """Successful operation inputs, including stable command context."""

    context: ExecutionContext
    params: dict[str, object]


def _safe_orthogonal_leader_route(
    position: Point2D,
    offsets: tuple[Point2D, ...],
    normal_vertex: Point2D,
    target: Point2D,
    *,
    avoid_crossing: bool = False,
    guard_box: bool = False,
    anchor: Point2D | None = None,
) -> tuple[Point2D, ...]:
    try:
        if guard_box:
            normal_offset = (normal_vertex[0] - position[0], normal_vertex[1] - position[1])
            return relocate_automatic_leader(
                position, (offsets[0], normal_offset), position, target, anchor=anchor
            )
        return reroute_orthogonal_leader(
            position, offsets, normal_vertex, target, avoid_crossing=avoid_crossing
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _translated_curve_reorders_referenced_points(
    before: tuple[Point2D, ...], after: tuple[Point2D, ...], indices: Sequence[int]
) -> bool:
    """Detect a point permutation combined with a uniform translation."""
    if len(before) != len(after) or not before:
        return False
    old_sorted, new_sorted = sorted(before), sorted(after)
    dx = new_sorted[0][0] - old_sorted[0][0]
    dy = new_sorted[0][1] - old_sorted[0][1]
    if not math.isfinite(dx) or not math.isfinite(dy) or (dx == 0 and dy == 0):
        return False

    def matches(old: Point2D, new: Point2D) -> bool:
        return math.isclose(old[0] + dx, new[0], rel_tol=0.0, abs_tol=1e-9) and math.isclose(
            old[1] + dy, new[1], rel_tol=0.0, abs_tol=1e-9
        )

    return all(matches(old, new) for old, new in zip(old_sorted, new_sorted, strict=True)) and any(
        0 <= index < len(before) and not matches(before[index], after[index]) for index in indices
    )


def _partially_translated_curve_reorders_referenced_points(
    before: tuple[Point2D, ...], after: tuple[Point2D, ...], indices: Sequence[int]
) -> bool:
    """Detect reordered points when two unchanged-index points establish a translation."""
    if len(before) != len(after) or len(before) < 3:
        return False
    offsets: dict[tuple[float, float], int] = {}
    for old, new in zip(before, after, strict=True):
        dx, dy = new[0] - old[0], new[1] - old[1]
        if math.isfinite(dx) and math.isfinite(dy):
            key = (round(dx, 9), round(dy, 9))
            offsets[key] = offsets.get(key, 0) + 1
    positions = {(round(point[0], 9), round(point[1], 9)) for point in after}
    for (dx, dy), count in offsets.items():
        if count < 2:
            continue
        for index in indices:
            if not 0 <= index < len(before):
                continue
            old, new = before[index], after[index]
            expected = (round(old[0] + dx, 9), round(old[1] + dy, 9))
            actual = (round(new[0], 9), round(new[1], 9))
            if expected != actual and expected in positions:
                return True
    return False


def _translated_curve_pair_swap_may_retarget(
    before: tuple[Point2D, ...], after: tuple[Point2D, ...], indices: Sequence[int]
) -> bool:
    """Detect a possible translated pair swap without assuming other points stay fixed."""
    if len(before) != len(after):
        return False
    if sum(old != new for old, new in zip(before, after, strict=True)) <= 1:
        # A single indexed point edit is a normal grip operation; it cannot be
        # distinguished from a translated swap that happens to leave one point fixed.
        return False
    dx, dy = after[0][0] - before[0][0], after[0][1] - before[0][1]
    if (
        math.isfinite(dx)
        and math.isfinite(dy)
        and all(
            math.isclose(old[0] + dx, new[0], rel_tol=0.0, abs_tol=1e-9)
            and math.isclose(old[1] + dy, new[1], rel_tol=0.0, abs_tol=1e-9)
            for old, new in zip(before, after, strict=True)
        )
    ):
        return False
    groups: dict[tuple[float, float], list[tuple[Point2D, Point2D]]] = {}
    sums: list[Point2D | None] = []
    for old, new in zip(before, after, strict=True):
        sx, sy = old[0] + new[0], old[1] + new[1]
        if not math.isfinite(sx) or not math.isfinite(sy):
            sums.append(None)
            continue
        key = (round(sx, 9), round(sy, 9))
        sums.append((sx, sy))
        point = (round(old[0], 9), round(old[1], 9))
        groups.setdefault(key, []).append(((sx, sy), point))
    work = 0
    for index in indices:
        if not 0 <= index < len(before):
            continue
        point_sum = sums[index]
        if point_sum is None:
            continue
        point = (round(before[index][0], 9), round(before[index][1], 9))
        x_keys = {round(point_sum[0] + offset, 9) for offset in (-1e-9, 0.0, 1e-9)}
        y_keys = {round(point_sum[1] + offset, 9) for offset in (-1e-9, 0.0, 1e-9)}
        for x_key in x_keys:
            for y_key in y_keys:
                for candidate_sum, candidate_point in groups.get((x_key, y_key), ()):
                    work += 1
                    if work > 200_000:
                        return True
                    if (
                        candidate_point != point
                        and math.isclose(point_sum[0], candidate_sum[0], rel_tol=0.0, abs_tol=1e-9)
                        and math.isclose(point_sum[1], candidate_sum[1], rel_tol=0.0, abs_tol=1e-9)
                    ):
                        return True
    return False


def _translated_curve_cycle_may_retarget(
    before: tuple[Point2D, ...], after: tuple[Point2D, ...], indices: Sequence[int]
) -> bool:
    """Conservatively detect a translated point cycle involving an attachment."""
    if len(before) != len(after) or len(before) < 3 or not indices:
        return False
    if sum(old != new for old, new in zip(before, after, strict=True)) <= 1:
        return False
    dx, dy = after[0][0] - before[0][0], after[0][1] - before[0][1]
    if (
        math.isfinite(dx)
        and math.isfinite(dy)
        and all(
            math.isclose(old[0] + dx, new[0], rel_tol=0.0, abs_tol=1e-9)
            and math.isclose(old[1] + dy, new[1], rel_tol=0.0, abs_tol=1e-9)
            for old, new in zip(before, after, strict=True)
        )
    ):
        return False
    # A whole-spline attachment may involve every control point. Refuse an
    # unprovable complex edit instead of spending quadratic, unbounded work.
    if len(before) * len(indices) > 200_000:
        return True
    old_indices: dict[tuple[float, float], list[int]] = {}
    for index, point in enumerate(before):
        key = (round(point[0], 9), round(point[1], 9))
        old_indices.setdefault(key, []).append(index)
    for index in indices:
        if 0 <= index < len(before):
            point = before[index]
            if len(old_indices[(round(point[0], 9), round(point[1], 9))]) > 1:
                return True
    work = 0
    for first in indices:
        if not 0 <= first < len(before):
            continue
        for second in range(len(before)):
            if second == first:
                continue
            dx = after[first][0] - before[second][0]
            dy = after[first][1] - before[second][1]
            if not math.isfinite(dx) or not math.isfinite(dy):
                continue
            pending = [(second, 2)]
            seen = {first, second}
            while pending:
                work += 1
                if work > 200_000:
                    return True
                current, depth = pending.pop()
                x, y = after[current][0] - dx, after[current][1] - dy
                # A point within the comparison tolerance may round into an
                # adjacent bucket. Search all buckets the tolerance can reach.
                x_keys = {round(x + offset, 9) for offset in (-1e-9, 0.0, 1e-9)}
                y_keys = {round(y + offset, 9) for offset in (-1e-9, 0.0, 1e-9)}
                candidates = (
                    index
                    for x_key in x_keys
                    for y_key in y_keys
                    for index in old_indices.get((x_key, y_key), ())
                )
                for next_index in candidates:
                    work += 1
                    if work > 200_000:
                        return True
                    if not (
                        math.isclose(
                            before[next_index][0] + dx, after[current][0], rel_tol=0.0, abs_tol=1e-9
                        )
                        and math.isclose(
                            before[next_index][1] + dy, after[current][1], rel_tol=0.0, abs_tol=1e-9
                        )
                    ):
                        continue
                    if next_index == first and depth >= 3:
                        return True
                    if next_index not in seen:
                        seen.add(next_index)
                        pending.append((next_index, depth + 1))
    return False


def _clipboard_text_styles(value: object, previous: TextStyleTable) -> TextStyleTable:
    candidate = TextStyleTable.from_mapping(value)
    if candidate.current_id != previous.current_id or any(
        candidate.get(style.style_id) != style for style in previous.styles
    ):
        raise ValueError("粘贴时不能修改已有文字样式。")
    return candidate


def _validate_transform_evidence_references(
    keys: set[tuple[str, str]],
    affected: tuple[CrossSketchTangency, ...],
    sketches: tuple[Sketch, ...],
    rectangle_transforms: Sequence[RectangleTransformEvidence],
    context: ExecutionContext | None,
) -> set[tuple[str, str]]:
    referenced = {
        (ref.sketch_id, ref.entity_id)
        for item in affected
        for ref in (item.first, item.second)
        if (ref.sketch_id, ref.entity_id) in keys
    }
    local_only = {
        (sketch.sketch_id, ref.entity_id)
        for sketch in sketches
        for constraint in sketch.constraints
        for ref in constraint.references
        if (sketch.sketch_id, ref.entity_id) in keys
    }
    supports_local = (
        context is not None
        and context.command_id == "drawing.sketch.revise"
        and context.command_version >= 30
    )
    standalone: set[tuple[str, str]] = (
        {(item.reference.sketch_id, item.reference.entity_id) for item in rectangle_transforms}
        if context is not None
        and context.command_id == "drawing.sketch.revise"
        and context.command_version >= 81
        else set()
    )
    if referenced != keys and not (supports_local and referenced | local_only | standalone == keys):
        raise ValueError("矩形变换依据没有关联的相切关系。")
    return referenced


class BuildKernel:
    """Geometry kernel facade: applies feature commands to an in-memory part.

    Implements the core ``ViewportPort`` protocol structurally: every
    successful ``apply`` freezes a snapshot of the post-execution part.
    """

    def __init__(self) -> None:
        self._reference_loader: Callable[[Mapping[str, object]], BuildKernel] | None = None
        self._references: dict[str, DocumentReference] = {}
        self._linked_sketches: dict[str, str] = {}
        self._drawing_state = DrawingState()
        self._drawing_rasters: dict[str, DrawingRaster] = {}
        self._drawing_groups = DrawingGroupTable()
        self._drawing_block_definitions: tuple[BlockDefinition, ...] = ()
        self._drawing_block_instances: tuple[BlockInstance, ...] = ()
        self._drawing_block_library_origins: tuple[BlockLibraryOrigin, ...] = ()
        self._drawing_projection_cache: dict[tuple[str, ViewBasis], ProjectionResult] = {}
        self._drawing_revision = 0
        self._part: Part | None = None
        self._snapshots: list[tuple[str, int, Part | None]] = []
        self._sketches: dict[str, Sketch] = {}
        self._cross_tangencies: dict[str, CrossSketchTangency] = {}
        self._associative_arrays: dict[str, AssociativeRectArray] = {}
        self._spatial_outputs: dict[str, tuple[str, object]] = {}
        self._spatial_names: dict[str, str] = {}
        self._drawing_layers_override: SketchLayerTable | None = None
        self._dimension_layer = "DIM"
        self._drawing_dimension_styles = DimensionStyleTable((DimensionStyle("标准"),), "标准")
        self._drawing_texts: dict[str, DrawingText] = {}
        self._drawing_text_styles = TextStyleTable()
        self._tolerance_frames: dict[str, FeatureControlFrame] = {}
        self._datum_identifiers: dict[str, DatumIdentifier] = {}
        self._reference_dimensions: dict[str, DetachedDimension] = {}
        self._drawing_fillet_baseline = 1.0
        self._drawing_fillet_radius = 1.0
        self._drawing_chamfer_angle_baseline = 45.0
        self._drawing_chamfer_values = (0.0, 0.0, 0.0, 45.0)
        self._operations: list[RecordedOperation] = []
        self._active_execution_context: ExecutionContext | None = None
        self._design_faces = DesignFaces()
        self._body_origins: tuple[BodyOrigin, ...] = ()
        self._geometry_revision = 0
        self._cache_generation = 0
        self._current_mesh_cache: OrderedDict[CurrentMeshCacheKey, Tessellation] = OrderedDict()
        self._history_mesh_cache: OrderedDict[HistoryMeshCacheKey, Tessellation] = OrderedDict()
        self._current_boundary_cache: OrderedDict[
            CurrentMeshCacheKey, tuple[ViewportBoundaryEdge, ...]
        ] = OrderedDict()
        self._history_boundary_cache: OrderedDict[
            HistoryMeshCacheKey, tuple[ViewportBoundaryEdge, ...]
        ] = OrderedDict()
        self._current_topology_cache: OrderedDict[CurrentMeshCacheKey, ViewportTopology] = (
            OrderedDict()
        )
        self._history_topology_cache: OrderedDict[HistoryMeshCacheKey, ViewportTopology] = (
            OrderedDict()
        )
        self._identity_scope = RuntimeIdentityScope()
        self._feature_ids: list[FeatureId] = []
        self._body_ids: tuple[BodyId, ...] = ()
        self._boundary_topology_ids: dict[tuple[int, int, int], TopologyId] = {}
        self._face_topology_ids: dict[tuple[int, int, int], TopologyId] = {}
        self._vertex_topology_ids: dict[tuple[int, int, int], TopologyId] = {}
        self._history_body_ids: dict[int, tuple[BodyId, ...]] = {}
        self._last_topology_evolution: TopologyEvolution | None = None
        self._pending_topology_evolution: TopologyEvolution | None = None

    def set_drawing_fillet_baseline(self, radius: float) -> None:
        """Initialize the drawing radius immediately after a kernel reset."""
        if not math.isfinite(radius) or radius < 0:
            raise ValueError("drawing fillet baseline must be finite and nonnegative")
        self._drawing_fillet_baseline = radius
        self._drawing_fillet_radius = radius

    def set_drawing_chamfer_angle_baseline(self, angle: float) -> None:
        """Initialize the drawing chamfer angle immediately after a reset."""
        if not math.isfinite(angle) or not 0 <= angle < 180:
            raise ValueError("drawing chamfer angle baseline must be in [0, 180)")
        self._drawing_chamfer_angle_baseline = angle
        self._drawing_chamfer_values = (0.0, 0.0, 0.0, angle)

    def reset(self) -> None:
        """Drop the current solid and the snapshot list: empty-geometry state."""
        # Snapshot list joins the cleared state: undo/redo rebuild resets the
        # kernel first, so full replay re-populates snapshots in ordinal order.

        self._part = None
        self._references = {}
        self._linked_sketches = {}
        self._drawing_state = DrawingState()
        self._drawing_rasters = {}
        self._drawing_groups = DrawingGroupTable()
        self._drawing_block_definitions = ()
        self._drawing_block_instances = ()
        self._drawing_block_library_origins = ()
        self._drawing_revision = 0
        self._snapshots = []
        self._sketches = {}
        self._cross_tangencies = {}
        self._associative_arrays = {}
        self._spatial_outputs = {}
        self._spatial_names = {}
        self._drawing_layers_override = None
        self._dimension_layer = "DIM"
        self._drawing_dimension_styles = DimensionStyleTable((DimensionStyle("标准"),), "标准")
        self._drawing_texts = {}
        self._drawing_text_styles = TextStyleTable()
        self._tolerance_frames = {}
        self._datum_identifiers = {}
        self._reference_dimensions = {}
        self._drawing_fillet_baseline = 1.0
        self._drawing_fillet_radius = 1.0
        self._drawing_chamfer_angle_baseline = 45.0
        self._drawing_chamfer_values = (0.0, 0.0, 0.0, 45.0)
        self._operations = []
        self._active_execution_context = None
        self._design_faces = DesignFaces()
        self._body_origins = ()
        self._last_topology_evolution = None
        self._pending_topology_evolution = None
        self._identity_scope.invalidate_topology()
        self._feature_ids = []
        self._body_ids = ()
        self._boundary_topology_ids.clear()
        self._face_topology_ids.clear()
        self._vertex_topology_ids.clear()
        self._history_body_ids.clear()
        self._geometry_revision += 1
        self._cache_generation += 1
        self._current_mesh_cache.clear()
        self._history_mesh_cache.clear()
        self._current_boundary_cache.clear()
        self._history_boundary_cache.clear()
        self._current_topology_cache.clear()
        self._history_topology_cache.clear()

    def replace_state_from(self, candidate: BuildKernel) -> None:
        """Install a fully rebuilt candidate without replaying into this kernel.

        The composition root uses this as the commit step for opening a
        document. All geometry work happens on ``candidate`` first, so this
        operation only copies the completed state references into the stable
        application kernel.
        """
        snapshots = candidate._snapshots.copy()
        part = candidate._part
        sketches = dict(candidate._sketches)
        self._identity_scope.invalidate_topology()
        self._boundary_topology_ids.clear()
        self._face_topology_ids.clear()
        self._vertex_topology_ids.clear()
        self._history_body_ids.clear()
        self._feature_ids = [
            self._identity_scope.new_feature_id() for _feature in candidate._feature_ids
        ]
        solid_count = 0 if part is None else len(part.solids())
        self._body_ids = tuple(self._identity_scope.new_body_id() for _ in range(solid_count))
        current_revision = max(self._geometry_revision, candidate._geometry_revision) + 1
        if snapshots:
            revision_offset = current_revision - snapshots[-1][1]
            snapshots = [
                (state_id, revision + revision_offset, snapshot_part)
                for state_id, revision, snapshot_part in snapshots
            ]
        self._geometry_revision = current_revision
        self._cache_generation += 1
        self._part, self._snapshots, self._sketches = part, snapshots, sketches
        self._cross_tangencies = dict(candidate._cross_tangencies)
        self._associative_arrays = dict(candidate._associative_arrays)
        self._last_topology_evolution = None
        self._pending_topology_evolution = None
        self._drawing_layers_override = candidate._drawing_layers_override
        self._dimension_layer = candidate._dimension_layer
        self._drawing_dimension_styles = candidate._drawing_dimension_styles
        self._drawing_texts = dict(candidate._drawing_texts)
        self._drawing_text_styles = candidate._drawing_text_styles
        self._tolerance_frames = dict(candidate._tolerance_frames)
        self._datum_identifiers = dict(candidate._datum_identifiers)
        self._reference_dimensions = dict(candidate._reference_dimensions)
        self._drawing_fillet_baseline = candidate._drawing_fillet_baseline
        self._drawing_fillet_radius = candidate._drawing_fillet_radius
        self._drawing_chamfer_angle_baseline = candidate._drawing_chamfer_angle_baseline
        self._drawing_chamfer_values = candidate._drawing_chamfer_values
        self._drawing_state = candidate._drawing_state
        self._drawing_rasters = dict(candidate._drawing_rasters)
        self._drawing_groups = candidate._drawing_groups
        self._drawing_block_definitions = candidate._drawing_block_definitions
        self._drawing_block_instances = candidate._drawing_block_instances
        self._drawing_block_library_origins = candidate._drawing_block_library_origins
        self._drawing_revision = candidate._drawing_revision
        self._operations = deepcopy(candidate._operations)
        self._spatial_outputs = dict(candidate._spatial_outputs)
        self._spatial_names = dict(candidate._spatial_names)
        # Faces belong to candidate._part; copying only them breaks native IsSame.
        self._design_faces = candidate._design_faces
        self._references = deepcopy(candidate._references)
        self._linked_sketches = dict(candidate._linked_sketches)
        self._body_origins = candidate._body_origins
        self._current_mesh_cache.clear()
        self._history_mesh_cache.clear()
        self._current_boundary_cache.clear()
        self._history_boundary_cache.clear()
        self._current_topology_cache.clear()
        self._history_topology_cache.clear()

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        """Apply and retain only successful inputs for deterministic regeneration."""
        self.apply_with_context(command_id, params, ExecutionContext(command_id))

    def validate_datum_revision_versioned(
        self, command_id: str, params: Mapping[str, object], version: int
    ) -> None:
        """Check versioned evidence before applying the existing attachment guard."""
        verified: frozenset[tuple[str, str]] = (
            self._validate_polyline_topology_evidence(params, command_id, version=version)
            if command_id == "drawing.sketch.revise" and version >= 57
            else frozenset()
        )
        self.validate_datum_revision(command_id, params, verified_exact=verified)

    def _validate_polyline_topology_evidence(
        self, params: Mapping[str, object], command_id: str, *, version: int = 0
    ) -> frozenset[tuple[str, str]]:
        """Validate exact reorder evidence, without relaxing existing guards."""
        records = params.get("polyline_topology_maps", ())
        if not isinstance(records, list | tuple):
            raise ValidationError("拓扑证据必须是数组。", command_id=command_id)
        if not records:
            return frozenset()
        if set(params) - {
            "revisions",
            "polyline_topology_maps",
            "remove_tangencies",
            "cross_tangencies",
        }:
            raise ValidationError("多段线拓扑映射不能与其他批量操作混合。", command_id=command_id)
        revisions = params.get("revisions")
        if not isinstance(revisions, list | tuple):
            raise ValidationError("拓扑证据缺少草图修订。", command_id=command_id)
        try:
            by_sketch: dict[str, Mapping[str, object]] = {}
            for value in cast("Sequence[object]", revisions):
                if not isinstance(value, Mapping):
                    raise ValueError("草图修订不是对象。")
                revision = cast("Mapping[str, object]", value)
                identity = revision.get("sketch_id")
                if not isinstance(identity, str) or identity in by_sketch:
                    raise ValueError("草图身份缺失或重复。")
                by_sketch[identity] = revision
            seen: set[tuple[str, str]] = set()
            for value in cast("Sequence[object]", records):
                if not isinstance(value, Mapping):
                    raise ValueError("映射不是对象。")
                record = cast("Mapping[str, object]", value)
                if set(record) != {"sketch_id", "mapping"}:
                    raise ValueError("映射字段无效。")
                sketch_id = record["sketch_id"]
                if not isinstance(sketch_id, str) or sketch_id not in by_sketch:
                    raise ValueError("映射没有对应草图修订。")
                mapping = PolylineTopologyMap.from_mapping(record["mapping"])
                key = (sketch_id, mapping.entity_id)
                if key in seen:
                    raise ValueError("图元映射重复。")
                seen.add(key)
                current = self._sketches[sketch_id]
                revision = by_sketch[sketch_id]
                if revision.get("base_state_sha256") != current.local_state_digest():
                    raise ValueError("草图修订已过期。")
                state = current.to_state_mapping()
                state["entities"], state["constraints"] = (
                    revision.get("entities"),
                    revision.get("constraints"),
                )
                revised = Sketch.from_mapping(state)
                old = next((item for item in current.entities if item.entity_id == key[1]), None)
                new = next((item for item in revised.entities if item.entity_id == key[1]), None)
                if not isinstance(old, PolylineEntity) or not isinstance(new, PolylineEntity):
                    raise ValueError("映射对象不是同一多段线。")
                source_layer = self.drawing_layers.get(old.layer_name)
                if source_layer.locked or source_layer.frozen or not source_layer.displayed:
                    raise ValueError("多段线位于锁定、冻结或隐藏图层。")
                mapping.validate_exact_reorder(old, new)
                from mycad.core.geometric_tolerance_attachment import resolve_attachment_local

                for attachment in (
                    *(datum.attachment for datum in self._datum_identifiers.values()),
                    *(frame.leader_attachment for frame in self._tolerance_frames.values()),
                ):
                    if (
                        attachment is None
                        or (attachment.sketch_id, attachment.reference.entity_id) != key
                    ):
                        continue
                    mapped = mapping.remap_checked(attachment, old, new)
                    if resolve_attachment_local(attachment, {key[1]: old}) is None or (
                        resolve_attachment_local(mapped, {key[1]: new}) is None
                    ):
                        raise ValueError("附着位置无法验证。")
            old_relations = self.cross_sketch_tangencies
            changed_sketches: dict[str, Sketch] = {}
            for sketch_id, revision in by_sketch.items():
                current = self._sketches[sketch_id]
                state = current.to_state_mapping()
                state["entities"], state["constraints"] = (
                    revision.get("entities"),
                    revision.get("constraints"),
                )
                changed_sketches[sketch_id] = Sketch.from_mapping(state)
            previous = tuple(self._sketches.values())
            updated = tuple(changed_sketches.get(item.sketch_id, item) for item in previous)
            special: tuple[CrossSketchTangency, ...] = ()
            if version >= 79:
                generated = {
                    (ref.sketch_id, ref.entity_id)
                    for array in self.associative_arrays
                    for ref in (
                        *(member.target for member in array.members),
                        *(output.target for output in array.extra_outputs),
                    )
                }
                special = tuple(
                    relation
                    for relation in old_relations
                    if any(
                        (ref.sketch_id, ref.entity_id) in seen
                        for ref in (relation.first, relation.second)
                    )
                    and any(
                        (ref.sketch_id, ref.entity_id) in generated
                        for ref in (relation.first, relation.second)
                    )
                )
            special_ids = {item.relation_id for item in special}
            ordinary = tuple(item for item in old_relations if item.relation_id not in special_ids)
            ordinary_rebound, _ = rebind_committed_tangencies_for_edit(previous, updated, ordinary)
            mappings = {
                (cast("str", record["sketch_id"]), mapping.entity_id): mapping
                for value in cast("Sequence[object]", records)
                for record in (cast("Mapping[str, object]", value),)
                for mapping in (PolylineTopologyMap.from_mapping(record["mapping"]),)
            }
            special_rebound = (
                rebind_proven_array_tangencies(
                    previous, updated, special, mappings, allow_reversed_segments=True
                )
                if special
                else ()
            )
            rebound_by_id = {
                item.relation_id: item for item in (*ordinary_rebound, *special_rebound)
            }
            rebound = tuple(rebound_by_id[item.relation_id] for item in old_relations)
            expected = {
                old.relation_id: new
                for old, new in zip(old_relations, rebound, strict=True)
                if old != new
            }
            if any(
                identity in expected
                and not any(
                    (ref.sketch_id, ref.entity_id) in seen for ref in (old.first, old.second)
                )
                for old in old_relations
                for identity in (old.relation_id,)
            ):
                raise ValueError("相切重绑定与拓扑映射无关。")
            removals = params.get("remove_tangencies", ())
            additions = params.get("cross_tangencies", ())
            if not isinstance(removals, list | tuple) or not isinstance(additions, list | tuple):
                raise ValueError("相切重绑定字段无效。")
            removed = cast("Sequence[object]", removals)
            new_relations = tuple(
                CrossSketchTangency.from_mapping(item)
                for item in cast("Sequence[object]", additions)
            )
            if (
                len(removed) != len(expected)
                or any(not isinstance(item, str) for item in removed)
                or set(removed) != set(expected)
                or len(new_relations) != len(expected)
                or {item.relation_id: item for item in new_relations} != expected
            ):
                raise ValueError("相切重绑定与原线段不一致。")
            return frozenset(seen)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"拓扑证据无效：{exc}", command_id=command_id) from exc

    def validate_datum_revision(
        self,
        command_id: str,
        params: Mapping[str, object],
        *,
        verified_exact: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        """Reject detectable ambiguity in new edits without changing historical replay."""
        from mycad.core.geometric_tolerance_attachment import resolve_attachment_local

        if command_id == "drawing.sketch.revise":
            revisions = params.get("revisions")
            if not isinstance(revisions, (list, tuple)):
                return
            raw_revisions = cast("Sequence[object]", revisions)
        elif command_id == "sketch.revise":
            raw_revisions = (params,)
        else:
            return
        for raw in raw_revisions:
            if not isinstance(raw, Mapping):
                continue
            revision = cast("Mapping[str, object]", raw)
            sketch_id = revision.get("sketch_id")
            current = self._sketches.get(sketch_id) if isinstance(sketch_id, str) else None
            if current is None:
                continue
            state = current.to_state_mapping()
            state["entities"] = revision.get("entities")
            state["constraints"] = revision.get("constraints")
            try:
                revised = Sketch.from_mapping(state)
            except (KeyError, TypeError, ValueError):
                continue
            old = {entity.entity_id: entity for entity in current.entities}
            new = {entity.entity_id: entity for entity in revised.entities}
            attachments = (
                *(datum.attachment for datum in self._datum_identifiers.values()),
                *(frame.leader_attachment for frame in self._tolerance_frames.values()),
            )
            for attachment in attachments:
                if attachment is None or attachment.sketch_id != sketch_id:
                    continue
                if (attachment.sketch_id, attachment.reference.entity_id) in verified_exact:
                    continue
                if (
                    resolve_attachment_local(attachment, old) is None
                    and resolve_attachment_local(attachment, new) is not None
                ):
                    raise ValidationError(
                        "失关联的标注附着可能指向其他几何；请先解除附着并重新关联。",
                        command_id=command_id,
                    )
                before = old.get(attachment.reference.entity_id)
                after = new.get(attachment.reference.entity_id)
                if (
                    attachment.segment_kind == "rectangle"
                    and isinstance(before, RectangleEntity)
                    and isinstance(after, RectangleEntity)
                    and any(
                        (before.opposite_corner_mm[axis] - before.first_corner_mm[axis])
                        * (after.opposite_corner_mm[axis] - after.first_corner_mm[axis])
                        <= 0
                        for axis in (0, 1)
                    )
                ):
                    raise ValidationError(
                        "标注附着的矩形边方向变化；请先解除附着并重新关联。",
                        command_id=command_id,
                    )
                if isinstance(before, PolylineEntity) and isinstance(after, PolylineEntity):
                    previous_points, next_points = before.points_mm, after.points_mm
                elif isinstance(before, SplineEntity) and isinstance(after, SplineEntity):
                    previous_points, next_points = before.control_points_mm, after.control_points_mm
                else:
                    previous_points, next_points = (), ()
                reference = attachment.reference
                if (
                    reference.kind in ("start", "end")
                    and previous_points
                    and next_points
                    and len(previous_points) != len(next_points)
                ):
                    raise ValidationError(
                        "标注附着的曲线点数变化，端点身份无法确认；请先解除附着并重新关联。",
                        command_id=command_id,
                    )
                if reference.kind == "start":
                    indices = (0,)
                elif reference.kind == "end":
                    indices = (len(previous_points) - 1,)
                elif reference.kind == "vertex" and reference.index is not None:
                    indices = (reference.index,)
                elif (
                    reference.kind == "segment" and reference.index is not None and previous_points
                ):
                    indices = (reference.index, (reference.index + 1) % len(previous_points))
                elif attachment.curve_kind == "spline":
                    indices = tuple(range(len(previous_points)))
                else:
                    indices = ()
                if (
                    _translated_curve_reorders_referenced_points(
                        previous_points, next_points, indices
                    )
                    or _partially_translated_curve_reorders_referenced_points(
                        previous_points, next_points, indices
                    )
                    or _translated_curve_pair_swap_may_retarget(
                        previous_points, next_points, indices
                    )
                    or _translated_curve_cycle_may_retarget(previous_points, next_points, indices)
                ):
                    raise ValidationError(
                        "标注附着的曲线点序可能发生平移重排或无法确认；请先解除附着并重新关联。",
                        command_id=command_id,
                    )
                if (
                    isinstance(before, LineEntity)
                    and isinstance(after, LineEntity)
                    and before.start_mm == after.end_mm
                    and before.end_mm == after.start_mm
                ):
                    raise ValidationError(
                        "标注附着的直线端点发生反转；请先解除附着并重新关联。",
                        command_id=command_id,
                    )
                if (
                    isinstance(before, ArcEntity)
                    and isinstance(after, ArcEntity)
                    and attachment.reference.kind in ("start", "end", "geometry")
                    and before.center_mm == after.center_mm
                    and before.radius_mm == after.radius_mm
                    and math.isclose(
                        before.sweep_angle_deg, -after.sweep_angle_deg, rel_tol=0.0, abs_tol=1e-9
                    )
                    and math.isclose(
                        (
                            after.start_angle_deg
                            - before.start_angle_deg
                            - before.sweep_angle_deg
                            + 180
                        )
                        % 360
                        - 180,
                        0.0,
                        abs_tol=1e-9,
                    )
                ):
                    raise ValidationError(
                        "标注附着的圆弧方向发生反转；请先解除附着并重新关联。",
                        command_id=command_id,
                    )
                if attachment.reference.kind in ("start", "end"):
                    if isinstance(before, PolylineEntity) and isinstance(after, PolylineEntity):
                        previous_points, next_points = before.points_mm, after.points_mm
                    elif isinstance(before, SplineEntity) and isinstance(after, SplineEntity):
                        previous_points = before.control_points_mm
                        next_points = after.control_points_mm
                    else:
                        previous_points, next_points = (), ()
                    if previous_points:
                        index = 0 if attachment.reference.kind == "start" else -1
                        previous_point = previous_points[index]
                        if next_points[index] != previous_point and previous_point in next_points:
                            raise ValidationError(
                                "标注附着的曲线端点可能发生重排；请先解除附着并重新关联。",
                                command_id=command_id,
                            )
                if isinstance(before, SplineEntity) and isinstance(after, SplineEntity):
                    before_count = len(before.control_points_mm)
                    after_count = len(after.control_points_mm)
                    index = attachment.reference.index
                    if (
                        attachment.reference.kind == "vertex"
                        and index is not None
                        and before_count != after_count
                        and index < after_count
                    ):
                        raise ValidationError(
                            "样条控制点数量变化，标注附着可能指向其他位置；请先解除附着。",
                            command_id=command_id,
                        )
                    if before_count == after_count:
                        indices = (
                            range(before_count)
                            if attachment.curve_kind == "spline"
                            else (index,)
                            if attachment.reference.kind == "vertex" and index is not None
                            else ()
                        )
                        for point_index in indices:
                            if point_index >= before_count:
                                continue
                            point = before.control_points_mm[point_index]
                            if (
                                after.control_points_mm[point_index] != point
                                and point in after.control_points_mm
                            ):
                                raise ValidationError(
                                    "标注附着的样条控制点发生重排；请先解除附着并重新关联。",
                                    command_id=command_id,
                                )
                    continue
                if (
                    attachment.reference.kind not in ("vertex", "segment")
                    or attachment.reference.index is None
                ):
                    continue
                if not isinstance(before, PolylineEntity) or not isinstance(after, PolylineEntity):
                    continue
                if len(before.points_mm) != len(after.points_mm):
                    if attachment.reference.kind == "vertex" and attachment.reference.index < len(
                        after.points_mm
                    ):
                        raise ValidationError(
                            "标注附着的多段线顶点数量变化；请先解除附着并重新关联。",
                            command_id=command_id,
                        )
                    # Segment count changes already make the attachment unresolved.
                    continue
                indices = [attachment.reference.index]
                if attachment.reference.kind == "segment":
                    indices.append((attachment.reference.index + 1) % len(before.points_mm))
                for index in indices:
                    if index >= len(before.points_mm):
                        continue
                    point = before.points_mm[index]
                    if after.points_mm[index] != point and point in after.points_mm:
                        raise ValidationError(
                            "标注附着的多段线顶点可能发生重排；请先解除附着并重新关联。",
                            command_id=command_id,
                        )

    @property
    def execution_contexts(self) -> tuple[ExecutionContext, ...]:
        """Successful operation identities; no backend entities escape this DTO."""
        return tuple(operation.context for operation in self._operations)

    def apply_with_context(
        self, command_id: str, params: Mapping[str, object], context: ExecutionContext
    ) -> None:
        """Retain identity/version alongside successful operation inputs."""
        if context.command_id != command_id:
            raise ValidationError("execution context command mismatch", command_id=command_id)
        checked = checked_mapping(params, command_id)
        self._pending_topology_evolution = None
        recorded = deepcopy(dict(checked))
        previous = self._active_execution_context
        self._active_execution_context = context
        try:
            self._apply_operation(command_id, checked)
            if self._drawing_groups.groups:
                self._validate_drawing_group_arrays(self._drawing_groups.groups)
                known = frozenset(self._drawing_object_catalog().objects)
                removed = {
                    ref
                    for group in self._drawing_groups.groups
                    for ref in group.members
                    if ref not in known
                }
                if removed:
                    self._drawing_groups = self._drawing_groups.without_members(removed)
        finally:
            self._active_execution_context = previous
        self._operations.append(RecordedOperation(context, recorded))

    def set_reference_loader(self, loader: Callable[[Mapping[str, object]], BuildKernel]) -> None:
        self._reference_loader = loader

    @property
    def document_references(self) -> tuple[DocumentReference, ...]:
        return tuple(deepcopy(tuple(self._references.values())))

    @property
    def linked_sketch_ids(self) -> frozenset[str]:
        return frozenset(self._linked_sketches)

    def _apply_reference(self, command_id: str, params: Mapping[str, object]) -> None:
        identity = cast("str", params["reference_id"])
        if command_id == "reference.detach":
            if identity not in self._references:
                raise ValidationError("reference does not exist")
            self._references.pop(identity)
            self._linked_sketches = {
                k: v for k, v in self._linked_sketches.items() if v != identity
            }
            self._record_sketch_change(command_id)
            return
        reference = DocumentReference.from_mapping(params)
        if command_id == "reference.update":
            previous = self._references.get(identity)
            if (
                previous is None
                or previous.file_id != reference.file_id
                or previous.object_id != reference.object_id
            ):
                raise ValidationError("reference update identity does not match adopted source")
            candidate = BuildKernel()
            candidate._reference_loader = self._reference_loader
            candidate.set_drawing_fillet_baseline(self._drawing_fillet_baseline)
            candidate.set_drawing_chamfer_angle_baseline(self._drawing_chamfer_angle_baseline)
            for operation in self._operations:
                cid, payload = operation.context.command_id, operation.params
                if cid == "reference.attach" and payload.get("reference_id") == identity:
                    payload = reference.to_mapping()
                if cid == "reference.update" and payload.get("reference_id") == identity:
                    continue
                candidate.apply_with_context(cid, payload, operation.context)
            operations = self._operations
            snapshots = self._snapshots.copy()
            feature_ids = list(self._feature_ids)
            self.replace_state_from(candidate)
            self._operations = operations
            self._snapshots = snapshots
            self._feature_ids = feature_ids
            self._record_sketch_change(command_id)
            return
        if identity in self._references:
            raise ValidationError("reference already exists")
        if self._reference_loader is None:
            raise ValidationError("reference replay loader is not configured")
        source = self._reference_loader(reference.archive)
        if reference.kind == "sketch":
            sketch = next((s for s in source.sketches if s.sketch_id == reference.object_id), None)
            if sketch is None or identity in self._sketches:
                raise ValidationError("reference sketch is missing or instance identity collides")
            self._sketches[identity] = replace(sketch, sketch_id=identity)
            self._linked_sketches[identity] = identity
        else:
            if any(r.kind == "part" for r in self._references.values()):
                raise ValidationError("engineering drawing already has a source part")
            self._part = deepcopy(source._part)
            self._design_faces = DesignFaces()
            self._sketches.update(deepcopy(source._sketches))
            self._linked_sketches.update(dict.fromkeys(source._sketches, identity))
            self._body_origins = source._body_origins
            self._body_ids = tuple(self._identity_scope.new_body_id() for _ in source._body_ids)
        self._references[identity] = reference
        self._record_sketch_change(command_id)

    def _apply_operation(self, command_id: str, params: Mapping[str, object]) -> None:
        """Apply one feature command to the in-memory part.

        ``feature.box`` / ``feature.cylinder`` (T2) and the T5 feature
        layer (extrude / revolve / hole / hole_pattern / fillet /
        boolean_cut / boolean_intersect) share this entry point. ``mode`` selects the boolean
        behaviour where applicable: ``new`` replaces the current solid,
        ``add`` fuses into it, ``cut`` subtracts from it.

        On success a snapshot is frozen (plan todo 3): a deepcopy of the
        post-execution part appended as ``("<command id>:<snapshot
        index>", Part)``. The 0-based index equals the feature_history
        ordinal whenever the history holds only geometry-affecting
        commands — metadata and named-group annotations never enter the
        replay sequence (document.py), and undo/redo rebuild by full
        replay, so the list is naturally rebuilt in ordinal order.
        """

        checked = checked_mapping(params, command_id)
        self._pending_topology_evolution = None

        if command_id in ("datum.coordinate_system.create", "datum.plane.create"):
            context = self._active_execution_context
            if context is None or context.instance_id is None:
                raise ValidationError(
                    "datum requires a persistent command identity", command_id=command_id
                )
            if context.instance_id in self._spatial_outputs:
                raise ValidationError("duplicate spatial output identity", command_id=command_id)
            output = evaluate_datum(command_id, checked, self._spatial_outputs)
            self._spatial_outputs[context.instance_id] = output
            self._spatial_names[context.instance_id] = cast("str", checked["name"])
            self._record_sketch_change(command_id)
            return

        if command_id.startswith("reference."):
            self._apply_reference(command_id, checked)
            return

        if command_id.startswith(
            ("drawing.sheet.", "drawing.view.", "drawing.annotation.", "drawing.note.")
        ):
            try:
                candidate_drawing = apply_drawing_command(self._drawing_state, command_id, checked)
                if command_id in ("drawing.view.create", "drawing.view.update"):
                    for view in candidate_drawing.views:
                        if view.source.kind == "current_part":
                            if self._part is None or not self._part.solids():
                                raise ValueError("生成工程视图需要有效实体")
                        elif view.source.sketch_id not in self._sketches:
                            raise ValueError("草图来源不存在，请先完成草图")
            except (ValueError, TypeError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            self._drawing_state = candidate_drawing
            self._drawing_revision += 1
            self._snapshots.append(
                (f"{command_id}:{len(self._snapshots)}", self._geometry_revision, self._part)
            )
            return
        if command_id.startswith(("drawing.text.", "drawing.text_styles.")):
            self._apply_drawing_text(command_id, checked)
            return
        if command_id.startswith("drawing.group."):
            try:
                if command_id == "drawing.group.remove":
                    self._drawing_groups = self._drawing_groups.remove(
                        cast("str", checked["group_id"])
                    )
                else:
                    group = DrawingGroup.from_mapping(checked)
                    validate_group_members((group,), self._drawing_object_catalog())
                    candidate = (
                        self._drawing_groups.add(group)
                        if command_id == "drawing.group.create"
                        else self._drawing_groups.update(group)
                    )
                    self._drawing_groups = candidate
                self._drawing_revision += 1
                self._record_sketch_change(command_id)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            return
        if command_id.startswith(
            ("drawing.block_library.", "drawing.block.", "drawing.block_instance.")
        ):
            self._apply_drawing_block(command_id, checked)
            return
        if command_id == "drawing.tolerance.batch":
            self._apply_tolerance_batch(checked)
            return
        if command_id == "drawing.reference_dimensions.batch":
            self._apply_reference_dimensions(checked)
            return
        if command_id == "drawing.raster.batch":
            try:
                action = checked.get("action")
                candidate = dict(self._drawing_rasters)
                seen: set[str] = set()
                context = self._active_execution_context
                protect_layers = context is not None and context.command_version >= 2

                def check_layer(image: DrawingRaster) -> None:
                    layer = self.drawing_layers.get(image.layer_name)
                    if protect_layers and (layer.locked or not layer.displayed):
                        raise ValueError("图片所在图层已锁定或隐藏。")

                if action == "remove":
                    for identity in cast("list[str]", checked["image_ids"]):
                        if identity in seen or identity not in candidate:
                            raise ValueError("图片不存在或身份重复。")
                        seen.add(identity)
                        if protect_layers:
                            check_layer(candidate[identity])
                        del candidate[identity]
                else:
                    for value in cast("list[object]", checked["images"]):
                        image = DrawingRaster.from_mapping(value)
                        identity = image.image_id
                        if identity in seen or ((identity in candidate) != (action == "update")):
                            raise ValueError("图片身份重复或不存在。")
                        seen.add(identity)
                        if protect_layers and action == "update":
                            check_layer(candidate[identity])
                        check_layer(image)
                        candidate[identity] = image
                self._drawing_rasters = candidate
            except (ValueError, KeyError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            self._drawing_revision += 1
            self._snapshots.append(
                (f"{command_id}:{len(self._snapshots)}", self._geometry_revision, self._part)
            )
            return
        if command_id in {"drawing.raster.add", "drawing.raster.update", "drawing.raster.remove"}:
            try:
                identity = checked.get("image_id")
                if not isinstance(identity, str):
                    raise ValueError("图片身份无效。")
                existing = self._drawing_rasters.get(identity)
                if command_id == "drawing.raster.add" and existing is not None:
                    raise ValueError("图片身份已存在。")
                if command_id != "drawing.raster.add" and existing is None:
                    raise ValueError("图片不存在。")
                context = self._active_execution_context
                protect_layers = context is not None and context.command_version >= (
                    2 if command_id == "drawing.raster.remove" else 3
                )

                def check_image_layer(item: DrawingRaster) -> None:
                    layer = self.drawing_layers.get(item.layer_name)
                    if protect_layers and (layer.locked or not layer.displayed):
                        raise ValueError("图片所在图层已锁定或隐藏。")

                if protect_layers and existing is not None:
                    check_image_layer(existing)
                if command_id == "drawing.raster.remove":
                    del self._drawing_rasters[identity]
                else:
                    image = DrawingRaster.from_mapping(dict(checked))
                    check_image_layer(image)
                    self._drawing_rasters[identity] = image
            except (ValueError, KeyError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            self._drawing_revision += 1
            self._snapshots.append(
                (f"{command_id}:{len(self._snapshots)}", self._geometry_revision, self._part)
            )
            return
        if command_id == "drawing.layers.set":
            self._set_drawing_layers(checked)
            return
        if command_id == "drawing.clipboard.prepare":
            try:
                text_styles = (
                    _clipboard_text_styles(
                        checked["clipboard_text_styles"], self._drawing_text_styles
                    )
                    if "clipboard_text_styles" in checked
                    else self._drawing_text_styles
                )
                styles = DimensionStyleTable.from_mapping(checked["clipboard_styles"])
                for style in styles.styles:
                    if style.text_style_id is not None:
                        text_styles.get(style.text_style_id)
                previous = self._drawing_dimension_styles
                if styles.current_name != previous.current_name or any(
                    styles.get(style.name) != style for style in previous.styles
                ):
                    raise ValueError("粘贴时不能更改现有标注样式。")
            except (KeyError, ValueError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            self._set_drawing_layers(checked)
            self._drawing_dimension_styles = styles
            self._drawing_text_styles = text_styles
            return
        if command_id == "drawing.dimension_styles.set":
            try:
                table = DimensionStyleTable.from_mapping(checked)
                for style in table.styles:
                    if style.text_style_id is not None:
                        try:
                            self._drawing_text_styles.get(style.text_style_id)
                        except KeyError as exc:
                            raise ValueError("标注样式引用的文字样式不存在。") from exc
                updated: dict[str, Sketch] = {}
                for identity, sketch in self._sketches.items():
                    constraints: list[SketchConstraint] = []
                    for constraint in sketch.constraints:
                        if constraint.style_name is None:
                            constraints.append(constraint)
                            continue
                        style = table.get(constraint.style_name)
                        inherited_tolerance = (
                            style.angular_tolerance
                            if constraint.kind == "angle"
                            else style.linear_tolerance
                        )
                        selected_tolerance = constraint.tolerance or inherited_tolerance
                        if (
                            selected_tolerance.mode != "none"
                            and constraint.text_override is not None
                            and constraint.text_override.count("<>") != 1
                        ):
                            raise ValueError("启用公差的尺寸文字必须包含且只包含一个 <> 占位符。")
                        constraints.append(
                            replace(
                                constraint,
                                precision=style.precision,
                                scale=style.scale,
                                style_name=style.name,
                            )
                        )
                    updated[identity] = replace(sketch, constraints=tuple(constraints))
            except KeyError as exc:
                raise ValidationError(
                    "标注样式仍被尺寸使用，不能删除。", command_id=command_id
                ) from exc
            except ValueError as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            self._sketches = updated
            self._drawing_dimension_styles = table
            self._record_sketch_change(command_id)
            return
        if command_id == "drawing.chamfer_values.set":
            values = tuple(
                checked.get(key)
                for key in ("distance_first", "distance_second", "angle_length", "angle")
            )
            if any(
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or value < 0
                for value in values
            ):
                raise ValidationError("倒角参数必须是非负有限数值。", command_id=command_id)
            first, second, length, angle = (float(cast("int | float", value)) for value in values)
            if angle >= 180:
                raise ValidationError("倒角角度必须小于 180 度。", command_id=command_id)
            self._drawing_chamfer_values = (first, second, length, angle)
            self._snapshots.append(
                (f"{command_id}:{len(self._snapshots)}", self._geometry_revision, self._part)
            )
            return
        if command_id == "drawing.fillet_radius.set":
            radius = checked.get("radius")
            if (
                isinstance(radius, bool)
                or not isinstance(radius, int | float)
                or not math.isfinite(radius)
                or radius < 0
            ):
                raise ValidationError("圆角半径必须是非负有限数值。", command_id=command_id)
            self._drawing_fillet_radius = float(radius)
            self._snapshots.append(
                (f"{command_id}:{len(self._snapshots)}", self._geometry_revision, self._part)
            )
            return
        if command_id == "drawing.tangency.add":
            self._apply_cross_tangency(checked)
            return
        if command_id == "drawing.array.add":
            self._apply_associative_array(checked)
            return
        if command_id == "drawing.array.update":
            self._update_associative_array(checked)
            return
        if command_id == "drawing.array.resize":
            self._resize_associative_array(checked)
            return
        if command_id == "drawing.array.move":
            self._move_associative_array(checked)
            return
        if command_id == "drawing.array.batch_override":
            self._set_array_batch_override(checked)
            return
        if command_id == "drawing.array.offset":
            self._set_array_member_offsets(checked)
            return
        if command_id == "drawing.array.rotate":
            self._set_array_member_rotations(checked)
            return
        if command_id == "drawing.array.reset":
            self._reset_array_member_overrides(checked)
            return
        if command_id == "drawing.array.erase":
            self._erase_array_members(checked)
            return
        if command_id == "drawing.array.replace":
            self._replace_array_members(checked)
            return
        if command_id == "drawing.array.remove":
            identity = checked.get("array_id")
            if not isinstance(identity, str) or identity not in self._associative_arrays:
                raise ValidationError("关联阵列不存在。", command_id=command_id)
            self._associative_arrays = {
                key: array for key, array in self._associative_arrays.items() if key != identity
            }
            self._record_sketch_change(command_id)
            return
        if command_id == "drawing.tangency.remove":
            identity = checked.get("relation_id")
            if not isinstance(identity, str) or identity not in self._cross_tangencies:
                raise ValidationError("跨草图相切关系不存在。", command_id=command_id)
            self._cross_tangencies = {
                key: relation for key, relation in self._cross_tangencies.items() if key != identity
            }
            self._record_sketch_change(command_id)
            return
        if command_id == "drawing.curve_identity.upgrade":
            try:
                sketch_id = cast("str", checked["sketch_id"])
                if sketch_id in self._linked_sketches:
                    raise ValueError("关联草图只读，不能升级曲线身份。")
                current = self._sketches[sketch_id]
                records = tuple(
                    CurvePointIdentities.from_mapping(raw)
                    for raw in cast("Sequence[object]", checked["records"])
                )
                entities = {entity.entity_id: entity for entity in current.entities}
                for record in records:
                    entity = entities.get(record.entity_id)
                    if entity is None:
                        raise ValueError("升级目标图元不存在。")
                    layer = self.drawing_layers.get(entity.layer_name)
                    if layer.locked or layer.frozen or not layer.displayed:
                        raise ValueError("升级目标位于锁定、冻结或隐藏图层。")
                upgraded = apply_curve_identity_upgrade(
                    current, cast("str", checked["base_state_sha256"]), records
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            self._sketches = {**self._sketches, sketch_id: upgraded}
            self._record_sketch_change(command_id)
            return
        if command_id == "sketch.create":
            create_rasters: dict[str, DrawingRaster] | None = None
            if "raster_batch" in checked:
                try:
                    batch = cast("Mapping[str, object]", checked["raster_batch"])
                    create_rasters = dict(self._drawing_rasters)
                    create_layers = merge_layer_tables(
                        SketchLayerTable.from_mapping(checked["layers"]), self.drawing_layers
                    )
                    for raw_image in cast("list[object]", batch["images"]):
                        image = DrawingRaster.from_mapping(raw_image)
                        if image.image_id in create_rasters:
                            raise ValueError("图片身份重复或已存在。")
                        layer = create_layers.get(image.layer_name)
                        context = self._active_execution_context
                        if (
                            context is not None
                            and context.command_version >= 56
                            and (layer.locked or not layer.displayed)
                        ):
                            raise ValueError("图片所在图层已锁定或隐藏。")
                        create_rasters[image.image_id] = image
                except (TypeError, ValueError, KeyError) as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
            previous_styles = self._drawing_dimension_styles
            previous_text_styles = self._drawing_text_styles
            if "clipboard_styles" in checked:
                try:
                    text_styles = (
                        _clipboard_text_styles(
                            checked["clipboard_text_styles"], previous_text_styles
                        )
                        if "clipboard_text_styles" in checked
                        else previous_text_styles
                    )
                    styles = DimensionStyleTable.from_mapping(checked["clipboard_styles"])
                    for style in styles.styles:
                        if style.text_style_id is not None:
                            text_styles.get(style.text_style_id)
                    if styles.current_name != previous_styles.current_name or any(
                        styles.get(style.name) != style for style in previous_styles.styles
                    ):
                        raise ValueError("粘贴时不能更改现有标注样式。")
                except (KeyError, ValueError) as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
                self._drawing_dimension_styles = styles
                self._drawing_text_styles = text_styles
            sketch_params = {
                key: value
                for key, value in checked.items()
                if key not in ("raster_batch", "clipboard_styles", "clipboard_text_styles")
            }
            try:
                if "cross_tangencies" in sketch_params or "associative_arrays" in sketch_params:
                    self._create_sketch_with_cross_tangencies(sketch_params)
                else:
                    self._create_sketch(sketch_params)
            except Exception:
                self._drawing_dimension_styles = previous_styles
                self._drawing_text_styles = previous_text_styles
                raise
            if create_rasters is not None:
                self._drawing_rasters = create_rasters
            return
        if command_id == "drawing.sketch.revise":
            revisions = cast("list[Mapping[str, object]]", checked["revisions"])
            context = self._active_execution_context
            topology_records = (
                cast("Sequence[Mapping[str, object]]", checked.get("polyline_topology_maps", ()))
                if context is not None and context.command_version >= 57
                else ()
            )
            verified_exact: frozenset[tuple[str, str]] = (
                self._validate_polyline_topology_evidence(
                    checked,
                    command_id,
                    version=context.command_version if context is not None else 0,
                )
                if topology_records
                else frozenset()
            )
            raster_candidate: dict[str, DrawingRaster] | None = None
            if "raster_batch" in checked:
                try:
                    batch = cast("Mapping[str, object]", checked["raster_batch"])
                    action = batch["action"]
                    raster_candidate = dict(self._drawing_rasters)
                    revision_seen: set[str] = set()
                    protect_rasters = context is not None and context.command_version >= 63

                    def check_raster_layer(image: DrawingRaster) -> None:
                        layer = self.drawing_layers.get(image.layer_name)
                        if protect_rasters and (layer.locked or not layer.displayed):
                            raise ValueError("图片所在图层已锁定或隐藏。")

                    if action == "remove":
                        for identity in cast("list[str]", batch["image_ids"]):
                            if identity in revision_seen or identity not in raster_candidate:
                                raise ValueError("图片不存在或身份重复。")
                            revision_seen.add(identity)
                            if protect_rasters:
                                check_raster_layer(raster_candidate[identity])
                            del raster_candidate[identity]
                    else:
                        for value in cast("list[object]", batch["images"]):
                            image = DrawingRaster.from_mapping(value)
                            identity = image.image_id
                            if identity in revision_seen or (
                                (identity in raster_candidate) != (action == "update")
                            ):
                                raise ValueError("图片身份重复或不存在。")
                            revision_seen.add(identity)
                            if protect_rasters and action == "update":
                                check_raster_layer(raster_candidate[identity])
                            check_raster_layer(image)
                            raster_candidate[identity] = image
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
            if (
                raster_candidate is not None
                or self._cross_tangencies
                or self._associative_arrays
                or "cross_tangencies" in checked
                or "remove_tangencies" in checked
                or "dimension" in checked
                or "associative_arrays" in checked
                or "erase_array_members" in checked
                or "rectangle_transforms" in checked
                or "polyline_transforms" in checked
                or "line_transforms" in checked
                or topology_records
            ):
                try:
                    raw_additions = checked.get("cross_tangencies", ())
                    raw_removals = checked.get("remove_tangencies", ())
                    if not isinstance(raw_additions, list | tuple) or not isinstance(
                        raw_removals, list | tuple
                    ):
                        raise ValueError("跨草图关系变更必须是数组。")
                    additions = tuple(
                        CrossSketchTangency.from_mapping(value)
                        for value in cast("Sequence[object]", raw_additions)
                    )
                    removals = cast("Sequence[object]", raw_removals)
                    if any(not isinstance(value, str) for value in removals):
                        raise ValueError("跨草图关系身份无效。")
                    self._apply_sketch_revisions(
                        revisions,
                        command_id=command_id,
                        additions=additions,
                        removals=cast("Sequence[str]", removals),
                        array_additions=tuple(
                            AssociativeRectArray.from_mapping(value)
                            for value in cast(
                                "Sequence[object]", checked.get("associative_arrays", ())
                            )
                        ),
                        dimension=cast("Mapping[str, object] | None", checked.get("dimension")),
                        erased_members=tuple(
                            ArrayEntityRef.from_mapping(value)
                            for value in cast(
                                "Sequence[object]", checked.get("erase_array_members", ())
                            )
                        ),
                        rectangle_transforms=tuple(
                            RectangleTransformEvidence.from_mapping(value)
                            for value in cast(
                                "Sequence[object]", checked.get("rectangle_transforms", ())
                            )
                        ),
                        polyline_transforms=tuple(
                            RectangleTransformEvidence.from_mapping(value)
                            for value in cast(
                                "Sequence[object]", checked.get("polyline_transforms", ())
                            )
                        ),
                        line_transforms=tuple(
                            RectangleTransformEvidence.from_mapping(value)
                            for value in cast(
                                "Sequence[object]", checked.get("line_transforms", ())
                            )
                        ),
                        topology_records=topology_records,
                        verified_exact=verified_exact,
                    )
                except (TypeError, ValueError) as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
            else:
                ids = [revision["sketch_id"] for revision in revisions]
                if len(set(ids)) != len(ids):
                    raise ValidationError("duplicate sketch revision", command_id=command_id)
                context = self._active_execution_context
                if context is not None and context.command_version >= 56:
                    previous_sketches = self._sketches
                    for revision in revisions:
                        self._apply_sketch_revision(revision, record=False)
                    if revisions:
                        self._record_sketch_change(command_id, previous_sketches=previous_sketches)
                else:
                    for index, revision in enumerate(revisions):
                        self._apply_sketch_revision(revision, record=index == len(revisions) - 1)
            if raster_candidate is not None:
                self._drawing_rasters = raster_candidate
            return
        if command_id == "sketch.revise":
            self._apply_sketch_revision(checked)
            return
        if command_id in ("sketch.constraint.add", "sketch.constraint.update"):
            self._apply_sketch_constraint(checked, command_id)
            return
        sketch_profile = checked.get("profile")
        context = self._active_execution_context or ExecutionContext(command_id)
        primitive_sources: list[Part] = []
        if is_bound_hole(command_id, checked):
            if context.command_version < 3 or context.instance_id is None:
                raise ValidationError("bound holes require identity-aware hole@3")
            reference = BoundFaceRef.from_mapping(checked["target_face"])
            face, point = self._design_faces.resolve_position(reference, checked["position"])
            if self._part is None:
                raise TopologyReferenceError(
                    "no bound face", reason="deleted", parameter_path="target_face"
                )
            candidate, evolution = apply_bound_hole(self._part, face, point, checked)
            self._capture_topology_evolution(evolution)
        elif (
            command_id == "feature.extrude"
            and isinstance(sketch_profile, Mapping)
            and cast("Mapping[str, object]", sketch_profile).get("type") == "sketch"
        ):
            candidate = apply_sketch_extrusion(self._part, self._sketches, checked)
        elif (
            command_id == "feature.revolve"
            and isinstance(sketch_profile, Mapping)
            and cast("Mapping[str, object]", sketch_profile).get("type") == "sketch"
        ):
            candidate = apply_sketch_revolve(self._part, self._sketches, checked)
        elif (
            command_id == "feature.hole"
            and isinstance(sketch_profile, Mapping)
            and cast("Mapping[str, object]", sketch_profile).get("type") == "sketch"
        ):
            candidate = apply_sketch_hole(
                self._part,
                self._sketches,
                checked,
                evolution_callback=self._capture_topology_evolution,
            )
        elif command_id in ("feature.box", "feature.cylinder", "feature.sphere"):
            candidate = apply_primitive(
                self._part,
                command_id,
                checked,
                evolution_callback=self._capture_topology_evolution
                if context.instance_id
                else None,
                primitive_callback=primitive_sources.append if context.instance_id else None,
            )
        else:
            candidate = apply_feature(
                self._part,
                command_id,
                checked,
                evolution_callback=self._capture_topology_evolution,
            )
        requires_one_solid = (
            command_id in ("feature.box", "feature.cylinder", "feature.sphere")
            and checked.get("mode", "new") == "new"
        )
        check = validate_result(candidate, command_id, require_single_solid=requires_one_solid)
        require_valid_result(check)
        design_faces = self._design_faces.evolve(
            self._part,
            candidate,
            context,
            checked,
            self._pending_topology_evolution,
            primitive_sources[0] if primitive_sources else None,
        )
        self._last_topology_evolution = self._pending_topology_evolution
        origins = operation_origins(
            self._part,
            candidate,
            self._body_origins,
            f"{command_id}:{len(self._snapshots)}",
            command_id,
            checked,
        )
        candidate_solid_count = 0 if candidate is None else len(candidate.solids())
        preserve_body_identity = (
            candidate_solid_count == 1 and len(self._body_ids) == 1 and not requires_one_solid
        )
        self._identity_scope.invalidate_topology()
        self._boundary_topology_ids.clear()
        self._face_topology_ids.clear()
        self._vertex_topology_ids.clear()
        self._history_body_ids.clear()
        self._history_boundary_cache.clear()
        self._history_topology_cache.clear()
        self._feature_ids.append(self._identity_scope.new_feature_id())
        self._body_ids = (
            self._body_ids
            if preserve_body_identity
            else tuple(
                self._identity_scope.new_body_id() for _index in range(candidate_solid_count)
            )
        )
        self._part = candidate
        self._design_faces = design_faces
        self._body_origins = origins
        # A successful complete cut is still a history step. Keep its empty
        # snapshot so the viewport never falls back to the previous solid.
        self._geometry_revision += 1
        self._current_mesh_cache.clear()
        self._current_boundary_cache.clear()
        self._current_topology_cache.clear()
        self._snapshots.append(
            (f"{command_id}:{len(self._snapshots)}", self._geometry_revision, deepcopy(self._part))
        )

    def _create_sketch_with_cross_tangencies(self, params: Mapping[str, object]) -> None:
        """Create one drawing sketch and its relations as one replayable command."""
        raw = params.get("cross_tangencies", ())
        raw_arrays = params.get("associative_arrays", ())
        for key, values in (("cross_tangencies", raw), ("associative_arrays", raw_arrays)):
            if not isinstance(values, list | tuple) or (key in params and not values):
                raise ValidationError("草图关系必须是非空数组。", command_id="sketch.create")
        base = {
            key: value
            for key, value in params.items()
            if key not in ("cross_tangencies", "associative_arrays")
        }
        if "support" in base or "support_face" in base:
            raise ValidationError("跨草图圆角暂不支持关联工作平面。", command_id="sketch.create")
        try:
            sketch = Sketch.from_mapping(base)
            if self._drawing_layers_override is not None:
                sketch = replace(
                    sketch, layers=merge_layer_tables(sketch.layers, self._drawing_layers_override)
                )
            relations = dict(self._cross_tangencies)
            for value in cast("Sequence[object]", raw):
                relation = CrossSketchTangency.from_mapping(value)
                if relation.relation_id in relations:
                    raise ValueError("相切关系身份已存在。")
                if sketch.sketch_id not in (relation.first.sketch_id, relation.second.sketch_id):
                    raise ValueError("新相切关系必须引用本次创建的草图。")
                other = (
                    relation.second
                    if relation.first.sketch_id == sketch.sketch_id
                    else relation.first
                )
                if other.sketch_id in self._linked_sketches:
                    raise ValueError("关联草图只读，不能添加跨草图相切。")
                relations[relation.relation_id] = relation
            if sketch.sketch_id in self._sketches:
                raise ValueError("草图身份已存在。")
            sketches = {**self._sketches, sketch.sketch_id: sketch}
            context = self._active_execution_context
            if (
                context is not None
                and context.command_version < 27
                and relations_use_rectangle_segments(
                    tuple(sketches.values()),
                    tuple(
                        relations[key] for key in relations.keys() - self._cross_tangencies.keys()
                    ),
                )
            ):
                raise ValueError("矩形边相切关系需要新版草图命令。")
            self._validate_cross_tangencies(sketches, relations)
            arrays = dict(self._associative_arrays)
            for value in cast("Sequence[object]", raw_arrays):
                array = AssociativeRectArray.from_mapping(value)
                if any(
                    ref.sketch_id != sketch.sketch_id
                    for ref in (
                        *[member.target for member in array.members],
                        *[output.target for output in array.extra_outputs],
                    )
                ):
                    raise ValueError("新阵列副本必须属于本次创建的草图。")
                self._validate_associative_array(array, sketches, arrays)
                arrays[array.array_id] = array
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id="sketch.create") from exc
        self._create_sketch(base)
        self._cross_tangencies = relations
        self._associative_arrays = arrays

    def _create_sketch(self, params: Mapping[str, object]) -> None:
        """Add one validated sketch projection to the Bus-replayed model state."""
        if "support" in params:
            support = cast("Mapping[str, object]", params["support"])
            frame = associated_frame(support, self._spatial_outputs)
            materialized = {key: value for key, value in params.items() if key != "support"}
            materialized["frame"] = frame.to_mapping()
            sketch = Sketch.from_mapping(materialized)
        else:
            sketch = Sketch.from_mapping(params)
        self._validate_dimension_style_references(sketch.constraints, "sketch.create")
        context = self._active_execution_context
        if context is not None and context.command_version >= 57:
            occupied_point_ids = {
                point_id
                for existing in self.sketches
                for item in existing.entities
                if isinstance(item, PolylineEntity | SplineEntity)
                for point_id in item.point_ids
            }
            for entity in sketch.entities:
                if isinstance(entity, PolylineEntity | SplineEntity) and entity.point_ids:
                    kind = "polyline" if isinstance(entity, PolylineEntity) else "spline"
                    expected = new_curve_point_identities(
                        entity.entity_id, kind, len(entity.point_ids)
                    )
                    valid = (
                        set(entity.point_ids) == set(expected)
                        if context.command_version >= 58
                        else entity.point_ids == expected
                    )
                    if not valid or (
                        context.command_version >= 58
                        and occupied_point_ids.intersection(entity.point_ids)
                    ):
                        raise ValidationError(
                            "新曲线点身份不符合该图元的确定性身份或与现有身份重复。",
                            command_id="sketch.create",
                        )
        if (
            context is not None
            and context.command_version < 27
            and has_rectangle_segment_tangency(sketch)
        ):
            raise ValidationError("矩形边相切约束需要新版草图命令。", command_id="sketch.create")
        reserved = {
            member.target.entity_id
            for array in self.associative_arrays
            for member in array.members
            if member.erased_index is not None
        }
        if any(entity.entity_id in reserved for entity in sketch.entities):
            raise ValidationError("已擦除阵列副本的身份被占用。", command_id="sketch.create")
        if sketch.support_face is not None:
            try:
                face = resolve_face(sketch.support_face.to_mapping(), self._part, "sketch.create")
                if face.geom_type != GeomType.PLANE:
                    raise ValueError("草图附着面必须是平面。")
                center = face.center(CenterOf.MASS)
                normal = face.normal_at(center).normalized()
                frame = WorkPlaneFrame.from_planar_face(
                    (float(center.X), float(center.Y), float(center.Z)),
                    (float(normal.X), float(normal.Y), float(normal.Z)),
                    u_hint=sketch.frame.u_axis,
                )
                sketch = Sketch(
                    sketch.sketch_id,
                    frame,
                    sketch.entities,
                    constraints=sketch.constraints,
                    layers=sketch.layers,
                    support_face=sketch.support_face,
                )
            except (MycadError, ValueError) as exc:
                raise ValidationError(
                    f"无法将草图重放到所选平面：{exc}", command_id="sketch.create"
                ) from exc
        if sketch.constraints:
            from mycad.core.cross_sketch_tangency import tangent_endpoints_satisfied
            from mycad.core.fillet_curves import tangent_on_curves
            from mycad.geom.sketch_constraints import (
                inferred_coincident_satisfied,
                measure_sketch_dimension,
                validate_sketch_revision_geometry,
            )

            try:
                if any(
                    item.kind in ("parallel", "perpendicular", "concentric", "equal", "fixed")
                    or (
                        item.source == "user"
                        and item.kind in ("horizontal", "vertical", "coincident", "tangent")
                    )
                    for item in sketch.constraints
                ):
                    validate_sketch_revision_geometry(sketch, sketch)
                for constraint in sketch.constraints:
                    if constraint.kind in (
                        "parallel",
                        "perpendicular",
                        "concentric",
                        "equal",
                        "fixed",
                    ) or (
                        constraint.source == "user"
                        and constraint.kind in ("horizontal", "vertical", "coincident", "tangent")
                    ):
                        if not constraint.driving:
                            raise ValueError("initial geometric relations must be driving")
                        continue
                    if constraint.source == "inferred":
                        if constraint.kind in ("horizontal", "vertical"):
                            reference = constraint.references[0]
                            entity = next(
                                item
                                for item in sketch.entities
                                if item.entity_id == reference.entity_id
                            )
                            if not isinstance(entity, LineEntity) or reference.kind != "geometry":
                                raise ValueError(
                                    f"inferred {constraint.kind} relation requires a line entity"
                                )
                            residual = (
                                abs(entity.start_mm[1] - entity.end_mm[1])
                                if constraint.kind == "horizontal"
                                else abs(entity.start_mm[0] - entity.end_mm[0])
                            )
                            tolerance = max(
                                1e-9,
                                math.dist(entity.start_mm, entity.end_mm) * 1e-10,
                            )
                            if residual > tolerance:
                                raise ValueError(
                                    f"inferred {constraint.kind} relation does not match geometry"
                                )
                        elif constraint.kind == "coincident":
                            if not inferred_coincident_satisfied(sketch, constraint):
                                raise ValueError(
                                    "inferred coincidence relation does not match geometry"
                                )
                        elif constraint.kind == "tangent":
                            if not constraint.driving or any(
                                reference.kind not in ("geometry", "segment")
                                for reference in constraint.references
                            ):
                                raise ValueError(
                                    "inferred tangent requires curve or segment references"
                                )
                            first, second = (
                                tangent_entity_curve(
                                    next(
                                        item
                                        for item in sketch.entities
                                        if item.entity_id == ref.entity_id
                                    ),
                                    ref.index if ref.kind == "segment" else None,
                                )
                                for ref in constraint.references
                            )
                            if not tangent_on_curves(
                                first, second
                            ) or not tangent_endpoints_satisfied(
                                first,
                                second,
                                constraint.first_endpoint,
                                constraint.second_endpoint,
                            ):
                                raise ValueError(
                                    "inferred tangent relation does not match geometry"
                                )
                        else:
                            raise ValueError("initial inferred relation kind is unsupported")
                        continue
                    if (
                        constraint.kind
                        not in (
                            "length",
                            "distance",
                            "angle",
                            "radius",
                            "diameter",
                        )
                        or constraint.value is None
                    ):
                        raise ValueError("initial sketch may contain only valued dimensions")
                    measured = measure_sketch_dimension(sketch, constraint)
                    if constraint.kind == "angle":
                        error = abs((measured - constraint.value + 180.0) % 360.0 - 180.0)
                        tolerance = 1e-7
                    else:
                        error = abs(measured - constraint.value)
                        tolerance = max(1e-7, abs(measured) * 1e-8)
                    if error > tolerance:
                        raise ValueError(
                            f"dimension {constraint.constraint_id[:8]} does not match its geometry"
                        )
            except ValueError as exc:
                raise ValidationError(
                    f"草图初始约束/标注未能通过几何校验：{exc}", command_id="sketch.create"
                ) from exc
        if sketch.sketch_id in self._sketches:
            raise ValidationError(
                f"sketch identity {sketch.sketch_id!r} already exists",
                command_id="sketch.create",
            )
        if self._drawing_layers_override is not None:
            sketch = replace(
                sketch, layers=merge_layer_tables(sketch.layers, self._drawing_layers_override)
            )
        self._sketches[sketch.sketch_id] = sketch
        self._record_sketch_change("sketch.create")

    def _apply_sketch_constraint(self, params: Mapping[str, object], command_id: str) -> None:
        """Replay a confirmed solved sketch state without loading its optional solver."""
        rebuild_consumers = (
            command_id == "sketch.constraint.update" or params.get("rebuild_consumers") is True
        )
        sketch_id = params.get("sketch_id")
        if isinstance(sketch_id, str) and sketch_id in self._linked_sketches:
            raise ValidationError("关联草图只读；请先解除关联再修改。", command_id=command_id)
        current = self._sketches.get(sketch_id) if isinstance(sketch_id, str) else None
        if current is None:
            raise ValidationError("constraint references a missing sketch", command_id=command_id)
        digest = params.get("base_state_sha256")
        context = self._active_execution_context
        local_digest = context is not None and (
            (command_id == "sketch.constraint.add" and context.command_version >= 4)
            or (command_id == "sketch.constraint.update" and context.command_version >= 2)
        )
        expected_digest = current.local_state_digest() if local_digest else current.state_digest()
        if digest != expected_digest:
            raise ValidationError(
                "constraint preview is stale; solve it again against the current sketch",
                command_id=command_id,
            )
        solver_id = params.get("solver_id")
        solver_version = params.get("solver_version")
        degrees_of_freedom = params.get("degrees_of_freedom")
        if solver_id != "planegcs" or not isinstance(solver_version, str) or not solver_version:
            raise ValidationError(
                "constraint command requires a recorded Planegcs solver version",
                command_id=command_id,
            )
        if isinstance(degrees_of_freedom, bool) or not isinstance(degrees_of_freedom, int):
            raise ValidationError(
                "constraint command requires an integer degrees-of-freedom result",
                command_id=command_id,
            )
        try:
            constraint = SketchConstraint.from_mapping(params.get("constraint"))
            self._validate_dimension_style_references((constraint,), command_id)
            raw_entities = params.get("solution_entities")
            if not isinstance(raw_entities, list | tuple):
                raise ValueError("solution_entities must be an array")
            solution_mapping: dict[str, object] = {
                "sketch_id": current.sketch_id,
                "frame": current.frame.to_mapping(),
                "layers": current.layers.to_mapping(),
                "entities": raw_entities,
            }
            solution = Sketch.from_mapping(solution_mapping)
            if (
                context is not None
                and context.command_version < (11 if command_id == "sketch.constraint.add" else 9)
                and any(
                    isinstance(entity, PolylineEntity | SplineEntity) and entity.point_ids
                    for entity in solution.entities
                )
            ):
                raise ValueError("带曲线点身份的求解结果需要新版约束命令版本。")
            validate_curve_identity_preservation(current, solution)
            if tuple(
                (item.entity_id, type(item), item.construction, item.layer_name)
                for item in solution.entities
            ) != tuple(
                (item.entity_id, type(item), item.construction, item.layer_name)
                for item in current.entities
            ):
                raise ValueError("solved sketch must preserve geometry identities and kinds")
            if any(
                reference.entity_id not in {item.entity_id for item in current.entities}
                for reference in constraint.references
            ):
                raise ValueError("constraint references missing sketch geometry")
            updated = (
                current.with_updated_constraint(constraint, solution.entities)
                if command_id == "sketch.constraint.update"
                else current.with_constraint(constraint, solution.entities)
            )
            if any(
                item.first_endpoint or item.second_endpoint or item.projection_axis is not None
                for item in updated.constraints
            ):
                from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

                updated = validate_sketch_revision_geometry(current, updated)
            if rebuild_consumers:
                from mycad.geom.sketch_constraints import refresh_reference_dimensions

                updated = refresh_reference_dimensions(updated)
        except ValueError as exc:
            raise ValidationError(
                f"invalid solved sketch constraint: {exc}",
                command_id=command_id,
            ) from exc
        sketches = {**self._sketches, current.sketch_id: updated}
        sketches = self._propagate_associative_arrays(sketches, command_id)
        preserve_normal_side = context is not None and (
            (command_id == "sketch.constraint.add" and context.command_version >= 10)
            or (command_id == "sketch.constraint.update" and context.command_version >= 8)
        )
        if preserve_normal_side:
            for identity, revised in sketches.items():
                if revised != self._sketches.get(identity):
                    state = revised.to_state_mapping()
                    self.validate_datum_revision(
                        "sketch.revise",
                        {
                            "sketch_id": identity,
                            "entities": state["entities"],
                            "constraints": state["constraints"],
                        },
                    )
        self._validate_cross_tangencies(sketches, self._cross_tangencies)
        if rebuild_consumers and updated.entities != current.entities:
            candidate = self._regenerate_with_sketches(sketches)
            self._validate_cross_tangencies(candidate._sketches, self._cross_tangencies)
            origins = operation_origins(
                self._part,
                candidate._part,
                self._body_origins,
                f"{command_id}:{len(self._snapshots)}",
                command_id,
                params,
                rebuild=True,
            )
            self._part = candidate._part
            self._design_faces = candidate._design_faces
            self._body_origins = origins
            sketches = candidate._sketches
            count = 0 if self._part is None else len(self._part.solids())
            self._body_ids = tuple(self._identity_scope.new_body_id() for _ in range(count))
        previous_sketches = self._sketches
        self._sketches = sketches
        self._record_sketch_change(
            command_id, previous_sketches=previous_sketches if preserve_normal_side else None
        )

    def _prepare_sketch_revision(
        self,
        params: Mapping[str, object],
        *,
        dimension: SketchConstraint | None = None,
        rectangle_transforms: Sequence[RectangleTransformEvidence] = (),
        verified_exact: frozenset[tuple[str, str]] = frozenset(),
    ) -> Sketch:
        """Validate a frozen local edit without changing kernel state."""
        from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

        sketch_id = params.get("sketch_id")
        if isinstance(sketch_id, str) and sketch_id in self._linked_sketches:
            raise ValidationError("关联草图只读；请先解除关联再修改。", command_id="sketch.revise")
        current = self._sketches.get(sketch_id) if isinstance(sketch_id, str) else None
        if current is None:
            raise ValidationError(
                "revision references a missing sketch", command_id="sketch.revise"
            )
        if params.get("base_state_sha256") != current.local_state_digest():
            raise ValidationError("sketch revision is stale", command_id="sketch.revise")
        mapping = current.to_state_mapping()
        mapping["entities"] = params.get("entities")
        mapping["constraints"] = params.get("constraints")
        try:
            revised = Sketch.from_mapping(mapping)
            validate_curve_identity_preservation(current, revised)
            removed_dimensions = {
                item.constraint_id for item in current.constraints if item.kind in DIMENSION_KINDS
            } - {item.constraint_id for item in revised.constraints if item.kind in DIMENSION_KINDS}
            for item in (*self._tolerance_frames.values(), *self._datum_identifiers.values()):
                ref = (
                    item.leader_annotation_attachment
                    if isinstance(item, FeatureControlFrame)
                    else item.annotation_attachment
                )
                if (
                    ref is not None
                    and ref.kind == "sketch_dimension"
                    and ref.sketch_id == current.sketch_id
                    and ref.object_id in removed_dimensions
                ):
                    raise ValueError("草图尺寸仍被标注附着；请先解除附着。")
            self._validate_dimension_style_references(revised.constraints, "sketch.revise")
            old_entities = {item.entity_id: item for item in current.entities}
            revised_entities = {item.entity_id: item for item in revised.entities}
            for datum in self._datum_identifiers.values():
                attachment = datum.attachment
                if (
                    attachment is not None
                    and (attachment.sketch_id, attachment.reference.entity_id) in verified_exact
                ):
                    continue
                if (
                    attachment is not None
                    and attachment.sketch_id == current.sketch_id
                    and attachment.curve_kind == "spline"
                ):
                    before_spline = old_entities.get(attachment.reference.entity_id)
                    after_spline = revised_entities.get(attachment.reference.entity_id)
                    if (
                        isinstance(before_spline, SplineEntity)
                        and isinstance(after_spline, SplineEntity)
                        and before_spline.control_points_mm != after_spline.control_points_mm
                        and len(before_spline.control_points_mm)
                        == len(after_spline.control_points_mm)
                        and sorted(before_spline.control_points_mm)
                        == sorted(after_spline.control_points_mm)
                    ):
                        raise ValueError("基准附着的样条控制点发生重排；请先重新关联。")
                if (
                    attachment is None
                    or attachment.sketch_id != current.sketch_id
                    or attachment.reference.kind != "segment"
                ):
                    continue
                before = old_entities.get(attachment.reference.entity_id)
                after = revised_entities.get(attachment.reference.entity_id)
                if isinstance(before, PolylineEntity) and isinstance(after, PolylineEntity):
                    reordered = (
                        before.points_mm != after.points_mm
                        and len(before.points_mm) == len(after.points_mm)
                        and sorted(before.points_mm) == sorted(after.points_mm)
                    )
                    if reordered or before.closed != after.closed:
                        raise ValueError("基准附着的多段线拓扑发生重排；请先重新关联到稳定几何。")
                if (
                    attachment.segment_kind == "rectangle"
                    and isinstance(before, RectangleEntity)
                    and isinstance(after, RectangleEntity)
                    and any(
                        (before.opposite_corner_mm[axis] - before.first_corner_mm[axis])
                        * (after.opposite_corner_mm[axis] - after.first_corner_mm[axis])
                        <= 0
                        for axis in (0, 1)
                    )
                ):
                    raise ValueError("基准附着的矩形边方向变化；请先重新关联。")
            evidence_by_id = {
                item.reference.entity_id: item
                for item in rectangle_transforms
                if item.reference.sketch_id == current.sketch_id
            }
            context = self._active_execution_context
            supports_rectangle_transform = (
                context is not None
                and context.command_id == "drawing.sketch.revise"
                and context.command_version >= 28
            )
            supports_local_rebind = (
                supports_rectangle_transform
                and context is not None
                and context.command_version >= 29
            )
            expected_constraints = (
                rebind_rectangle_constraints_for_sketch(
                    current,
                    revised,
                    tuple(rectangle_transforms),
                    adaptive_tolerance=context is not None and context.command_version >= 81,
                )
                if supports_local_rebind and rectangle_transforms
                else current.constraints
            )
            if (
                supports_local_rebind
                and rectangle_transforms
                and context is not None
                and context.command_version >= 81
            ):
                revised_constraint_ids = {item.constraint_id for item in revised.constraints}
                expected_constraints = tuple(
                    item
                    for item in expected_constraints
                    if item.source != "inferred" or item.constraint_id in revised_constraint_ids
                )
            expected_by_id = {item.constraint_id: item for item in expected_constraints}
            retained_local = {}
            if (
                context is not None
                and context.command_id == "drawing.sketch.revise"
                and context.command_version >= 41
            ):
                raw_removals = params.get("removed_local_tangencies", ())
                if not isinstance(raw_removals, list | tuple):
                    raise ValueError("移除的本地相切身份无效。")
                removal_values = cast("Sequence[object]", raw_removals)
                if any(not isinstance(identity, str) for identity in removal_values):
                    raise ValueError("移除的本地相切身份无效。")
                removed_local = set(cast("Sequence[str]", removal_values))
                if removed_local:
                    if context.command_version < 80 or len(removed_local) != len(removal_values):
                        raise ValueError("移除本地相切需要新版修订命令及唯一身份。")
                    old_by_id = {item.constraint_id: item for item in current.constraints}
                    revised_ids = {item.constraint_id for item in revised.constraints}
                    if any(
                        identity not in old_by_id
                        or old_by_id[identity].kind != "tangent"
                        or old_by_id[identity].source != "user"
                        or identity in revised_ids
                        for identity in removed_local
                    ):
                        raise ValueError("移除的本地相切不存在、类型不符或仍被保留。")
                retained_source = replace(
                    current,
                    constraints=tuple(
                        item
                        for item in current.constraints
                        if item.constraint_id not in removed_local
                    ),
                )
                retained_local = {
                    item.constraint_id: item
                    for item in rebind_retained_local_tangencies(
                        retained_source,
                        revised,
                        allow_fragment_rebind=context.command_version >= 42,
                        allow_split_lines=context.command_version >= 45,
                        allow_split_arcs=context.command_version >= 46,
                        allow_joint_similarity=context.command_version in (47, 49, 51, 52),
                    )
                    if item.kind == "tangent" and item.source == "user"
                }
                revised_by_id = {item.constraint_id: item for item in revised.constraints}
                if any(
                    revised_by_id.get(identity) != item for identity, item in retained_local.items()
                ):
                    raise ValueError("修剪后的相切段不符合唯一保留的切点。")
            if (
                supports_local_rebind
                and rectangle_transforms
                and (
                    len(expected_constraints) != len(revised.constraints)
                    or any(
                        before != after and not is_reference_value_refresh(before, after)
                        for before, after in zip(
                            expected_constraints, revised.constraints, strict=True
                        )
                    )
                )
            ):
                raise ValueError("矩形变换后的本地约束与依据不一致。")
            if any(
                (old := old_entities.get(item.entity_id)) is not None
                and type(old) is not type(item)
                and not (
                    context is not None
                    and context.command_id == "drawing.sketch.revise"
                    and context.command_version >= 39
                    and isinstance(old, CircleEntity)
                    and isinstance(item, ArcEntity)
                    and old.center_mm == item.center_mm
                    and old.radius_mm == item.radius_mm
                    and old.construction == item.construction
                    and old.layer_name == item.layer_name
                )
                and not (
                    supports_rectangle_transform
                    and (
                        supports_local_rebind
                        and isinstance(old, RectangleEntity)
                        and isinstance(item, PolylineEntity)
                        and old.construction == item.construction
                        and old.layer_name == item.layer_name
                        and item.entity_id in evidence_by_id
                        or rectangle_transform_kind_change_allowed(
                            current, old, item, evidence_by_id.get(item.entity_id)
                        )
                    )
                )
                for item in revised.entities
            ):
                raise ValueError("existing geometry identity cannot change kind")
            old_constraints = {item.constraint_id: item for item in current.constraints}
            supports_rectangle_tangency = context is not None and (
                (context.command_id == "drawing.sketch.revise" and context.command_version >= 27)
                or (context.command_id == "drawing.tangency.add" and context.command_version >= 6)
            )
            new_constraints = tuple(
                item
                for item in revised.constraints
                if old_constraints.get(item.constraint_id) != item
            )
            if not supports_rectangle_tangency and has_rectangle_segment_tangency(
                replace(revised, constraints=new_constraints)
            ):
                raise ValueError("矩形边相切约束需要新版草图修订命令。")
            if dimension is not None:
                allowed_constraint_kinds = (
                    "length",
                    "distance",
                    "radius",
                    "diameter",
                    "arc_length",
                    "angle",
                )
                if (
                    context is not None
                    and context.command_id == "drawing.sketch.revise"
                    and context.command_version >= 38
                ):
                    allowed_constraint_kinds = (*allowed_constraint_kinds, "tangent")
                if (
                    not dimension.driving
                    or dimension.kind not in allowed_constraint_kinds
                    or dimension.axis
                    not in ("aligned", "horizontal", "vertical", "ordinate_x", "ordinate_y")
                ):
                    raise ValueError("unsupported cross-sketch dimension")
                confirmed = (
                    current.with_updated_constraint(dimension, current.entities)
                    if dimension.constraint_id in old_constraints
                    else current.with_constraint(dimension, current.entities)
                )
                old_constraints = {item.constraint_id: item for item in confirmed.constraints}
                if dimension not in revised.constraints:
                    raise ValueError("confirmed dimension is absent from revised sketch")
                if len(revised.constraints) != len(confirmed.constraints) or any(
                    before != after and not is_reference_value_refresh(before, after)
                    for before, after in zip(
                        confirmed.constraints, revised.constraints, strict=True
                    )
                ):
                    raise ValueError("dimension revision changed another constraint")
            new_entity_ids = {item.entity_id for item in revised.entities} - set(old_entities)
            context = self._active_execution_context
            inferred_kinds = ("horizontal", "vertical", "coincident")
            if context is not None and (
                (context.command_id == "drawing.sketch.revise" and context.command_version >= 2)
                or (context.command_id == "sketch.revise" and context.command_version >= 4)
            ):
                inferred_kinds = (*inferred_kinds, "tangent")
            if any(
                old_constraints.get(item.constraint_id) != item
                and not (
                    context is not None
                    and context.command_id == "drawing.sketch.revise"
                    and context.command_version >= 54
                    and (prior := old_constraints.get(item.constraint_id)) is not None
                    and is_rigid_dimension_translation(prior, item, current, revised)
                    and not current.layers.get(
                        prior.layer_name or old_entities[prior.references[0].entity_id].layer_name
                    ).locked
                    and not current.layers.get(
                        prior.layer_name or old_entities[prior.references[0].entity_id].layer_name
                    ).frozen
                )
                and not (
                    context is not None
                    and context.command_id == "drawing.sketch.revise"
                    and context.command_version >= 52
                    and item.kind in DIMENSION_KINDS
                    and (previous := old_constraints.get(item.constraint_id)) is not None
                    and replace(item, layer_name=previous.layer_name) == previous
                )
                and not (
                    (old := old_constraints.get(item.constraint_id)) is not None
                    and is_reference_value_refresh(old, item)
                )
                and not (
                    supports_local_rebind
                    and (expected := expected_by_id.get(item.constraint_id)) is not None
                    and (expected == item or is_reference_value_refresh(expected, item))
                )
                and not (
                    item.kind == "tangent"
                    and item.source == "user"
                    and retained_local.get(item.constraint_id) == item
                )
                and not (
                    context is not None
                    and context.command_id == "drawing.sketch.revise"
                    and context.command_version >= 10
                    and (prior_constraint := old_constraints.get(item.constraint_id)) is not None
                    and (
                        is_unchanged_inferred_polyline_reference_rebind(
                            prior_constraint, item, current, revised
                        )
                        if context.command_version >= 32
                        else is_inferred_reference_rebind(prior_constraint, item, current, revised)
                    )
                )
                and not (
                    context is not None
                    and (
                        (context.command_id == "sketch.revise" and context.command_version >= 6)
                        or (
                            context.command_id == "drawing.sketch.revise"
                            and context.command_version >= 32
                        )
                    )
                    and (prior_user := old_constraints.get(item.constraint_id)) is not None
                    and is_unchanged_user_polyline_reference_rebind(
                        prior_user, item, current, revised
                    )
                )
                and not (
                    item.constraint_id not in old_constraints
                    and item.source == "inferred"
                    and item.driving
                    and item.kind in inferred_kinds
                    and any(ref.entity_id in new_entity_ids for ref in item.references)
                )
                for item in revised.constraints
            ):
                raise ValueError("new or modified constraints require separate confirmation")
            entity_ids = {item.entity_id for item in revised.entities}
            if any(
                reference.entity_id not in entity_ids
                for item in revised.constraints
                for reference in item.references
            ):
                raise ValueError("constraint references missing sketch geometry")
            submitted = revised
            revised = validate_sketch_revision_geometry(current, revised)
            for before, after in zip(submitted.constraints, revised.constraints, strict=True):
                old = old_constraints.get(before.constraint_id)
                if (
                    old is not None
                    and old != before
                    and is_reference_value_refresh(old, before)
                    and before != after
                ):
                    raise ValueError("reference dimension value does not match geometry")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id="sketch.revise") from exc
        return revised

    def _apply_sketch_revision(self, params: Mapping[str, object], *, record: bool = True) -> None:
        """Replay a frozen local edit while preserving surviving relation semantics."""
        if self._cross_tangencies or self._associative_arrays:
            self._apply_sketch_revisions((params,), command_id="sketch.revise", record=record)
            return
        revised = self._prepare_sketch_revision(params)
        current = self._sketches[revised.sketch_id]
        sketches = {**self._sketches, current.sketch_id: revised}
        candidate = self._regenerate_with_sketches(sketches)
        self._body_origins = operation_origins(
            self._part,
            candidate._part,
            self._body_origins,
            f"sketch.revise:{len(self._snapshots)}",
            "sketch.revise",
            params,
            rebuild=True,
        )
        self._part = candidate._part
        self._design_faces = candidate._design_faces
        self._sketches = candidate._sketches
        count = 0 if self._part is None else len(self._part.solids())
        self._body_ids = tuple(self._identity_scope.new_body_id() for _ in range(count))
        if record:
            self._record_sketch_change("sketch.revise")

    def _validate_cross_tangencies(
        self, sketches: Mapping[str, Sketch], relations: Mapping[str, CrossSketchTangency]
    ) -> None:
        values = tuple(relations.values())
        try:
            for relation in values:
                validate_tangency_component(
                    tuple(sketches.values()), values, relation.first.sketch_id
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"跨草图相切校验失败：{exc}") from exc

    def _propagate_associative_arrays(
        self,
        sketches: Mapping[str, Sketch],
        command_id: str,
        *,
        resulting_arrays: tuple[AssociativeRectArray, ...] | None = None,
        base_rebind_maps: Mapping[tuple[str, str], PolylineTopologyMap] | None = None,
        base_rebind_proofs: tuple[Sketch, ...] | None = None,
        proven_reorder_targets: frozenset[tuple[str, str]] = frozenset(),
    ) -> dict[str, Sketch]:
        if not self._associative_arrays:
            return dict(sketches)
        try:
            result = propagate_array_changes(
                tuple(self._sketches.values()),
                tuple(sketches.values()),
                self.associative_arrays,
                resulting_arrays=resulting_arrays,
                base_rebind_maps=base_rebind_maps,
                base_rebind_proofs=base_rebind_proofs,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        updated = {sketch.sketch_id: sketch for sketch in result}
        self._validate_array_cross_changes(updated, command_id, proven_reorder_targets)
        return updated

    def _validate_array_cross_changes(
        self,
        updated: Mapping[str, Sketch],
        command_id: str,
        proven_reorder_targets: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        try:
            for identity, revised in updated.items():
                previous = self._sketches.get(identity)
                if previous is not None:
                    validate_curve_identity_preservation(previous, revised)
            validate_array_cross_changes(
                self._sketches,
                updated,
                self.associative_arrays,
                self.cross_sketch_tangencies,
                proven_reorder_targets=proven_reorder_targets,
            )
        except (KeyError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc

    def _validate_attached_sketch_changes(self, sketches: Mapping[str, Sketch]) -> None:
        for identity, revised in sketches.items():
            if revised != self._sketches.get(identity):
                state = revised.to_state_mapping()
                self.validate_datum_revision(
                    "sketch.revise",
                    {
                        "sketch_id": identity,
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    },
                )

    def _reject_attached_array_replacements(self, changed: set[ArrayEntityRef]) -> None:
        affected = set(changed)
        while True:
            previous_count = len(affected)
            for array in self.associative_arrays:
                for member in array.members:
                    dependencies = {member.source}
                    if member.replacement is not None:
                        dependencies.add(member.replacement.source)
                        if member.replacement.anchor_source is not None:
                            dependencies.add(member.replacement.anchor_source)
                    if dependencies & affected:
                        affected.add(member.target)
                for output in array.extra_outputs:
                    if output.source in affected or output.anchor_source in affected:
                        affected.add(output.target)
            if len(affected) == previous_count:
                break
        for item in (*self._datum_identifiers.values(), *self._tolerance_frames.values()):
            attachment = (
                item.attachment if isinstance(item, DatumIdentifier) else item.leader_attachment
            )
            if (
                attachment is not None
                and ArrayEntityRef(attachment.sketch_id, attachment.reference.entity_id) in affected
            ):
                raise ValidationError(
                    "阵列操作会改变标注所附着的几何来源；请先解除附着并重新关联。"
                )

    def _update_associative_array(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.update"
        try:
            result, updated = update_array_spacing(
                tuple(self._sketches.values()),
                self.associative_arrays,
                cast("str", params["array_id"]),
                cast("float", params["row_spacing"]),
                cast("float", params["column_spacing"]),
                angle_deg=cast("float | None", params.get("angle_deg")),
                base_point=ArrayBasePoint.from_mapping(params["base_point"])
                if "base_point" in params
                else None,
                reset_base_point=cast("bool", params.get("reset_base_point", False)),
            )
            sketches = {sketch.sketch_id: sketch for sketch in result}
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(command_id)

    def _resize_associative_array(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.resize"
        try:
            updated = AssociativeRectArray.from_mapping(params.get("array"))
            context = self._active_execution_context
            previous = next(
                (array for array in self.associative_arrays if array.array_id == updated.array_id),
                None,
            )
            if (
                context is not None
                and context.command_version < 13
                and previous is not None
                and previous.extra_outputs != updated.extra_outputs
            ):
                raise ValueError("此数量调整版本不能删除额外输出。")
            candidate_arrays = tuple(
                updated if array.array_id == updated.array_id else array
                for array in self.associative_arrays
            )
            if (
                context is not None
                and context.command_version < 10
                and has_interleaved_array_dependencies(candidate_arrays)
            ):
                raise ValueError("此数量调整版本不支持交错阵列依赖。")
            if (
                context is not None
                and context.command_version < 9
                and has_internal_replacements(updated)
            ):
                raise ValueError("此数量调整版本不支持阵列内部替换依赖。")
            result = resize_array(tuple(self._sketches.values()), self.associative_arrays, updated)
            sketches = {sketch.sketch_id: sketch for sketch in result}
            if context is not None and context.command_version >= 16:
                self._validate_attached_sketch_changes(sketches)
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        previous_sketches = self._sketches
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(
            command_id,
            previous_sketches=previous_sketches
            if context is not None and context.command_version >= 16
            else None,
        )

    def _move_associative_array(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.move"
        try:
            from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

            raw = cast("Sequence[float]", params["displacement"])
            context = self._active_execution_context
            target_array = next(
                (
                    array
                    for array in self.associative_arrays
                    if array.array_id == params["array_id"]
                ),
                None,
            )
            extra_targets = {
                output.target for array in self.associative_arrays for output in array.extra_outputs
            }
            if (
                context is not None
                and context.command_version < 3
                and target_array is not None
                and set(target_array.sources) & extra_targets
            ):
                raise ValueError("此移动版本不支持额外输出作为阵列来源。")
            if context is not None and context.command_version >= 2:
                result, arrays = move_associative_array_with_offsets(
                    tuple(self._sketches.values()),
                    self.associative_arrays,
                    cast("str", params["array_id"]),
                    (raw[0], raw[1]),
                )
            else:
                result, updated = move_associative_array(
                    tuple(self._sketches.values()),
                    self.associative_arrays,
                    cast("str", params["array_id"]),
                    (raw[0], raw[1]),
                )
                arrays = tuple(
                    updated if item.array_id == updated.array_id else item
                    for item in self.associative_arrays
                )
            sketches = {
                sketch.sketch_id: validate_sketch_revision_geometry(
                    self._sketches[sketch.sketch_id], sketch
                )
                if sketch != self._sketches[sketch.sketch_id] and sketch.constraints
                else sketch
                for sketch in result
            }
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {item.array_id: item for item in arrays}
        self._record_sketch_change(command_id)

    def _set_array_batch_override(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.batch_override"
        try:
            from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

            offsets: dict[str, dict[ArrayEntityRef, tuple[float, float]]] = {}
            rotations: dict[str, dict[ArrayEntityRef, tuple[float, tuple[float, float]]]] = {}
            for group in cast("Sequence[Mapping[str, object]]", params["groups"]):
                array_id = cast("str", group["array_id"])
                if array_id in offsets or array_id in rotations:
                    raise ValueError("阵列批量修改包含重复阵列。")
                if params["operation"] == "offset":
                    entries: dict[ArrayEntityRef, tuple[float, float]] = {}
                    for raw in cast("Sequence[Mapping[str, object]]", group["members"]):
                        target = ArrayEntityRef.from_mapping(raw["target"])
                        if target in entries:
                            raise ValueError("阵列批量修改包含重复成员。")
                        point = cast("Sequence[float]", raw["offset_mm"])
                        entries[target] = (point[0], point[1])
                    offsets[array_id] = entries
                else:
                    rotated: dict[ArrayEntityRef, tuple[float, tuple[float, float]]] = {}
                    for raw in cast("Sequence[Mapping[str, object]]", group["members"]):
                        target = ArrayEntityRef.from_mapping(raw["target"])
                        if target in rotated:
                            raise ValueError("阵列批量修改包含重复成员。")
                        point = cast("Sequence[float]", raw["center_offset_mm"])
                        rotated[target] = (cast("float", raw["angle_deg"]), (point[0], point[1]))
                    rotations[array_id] = rotated
            original = tuple(self._sketches.values())
            result, arrays = (
                set_array_offsets_batch(original, self.associative_arrays, offsets)
                if params["operation"] == "offset"
                else set_array_rotations_batch(original, self.associative_arrays, rotations)
            )
            sketches = {
                sketch.sketch_id: validate_sketch_revision_geometry(
                    self._sketches[sketch.sketch_id], sketch
                )
                if sketch != self._sketches[sketch.sketch_id] and sketch.constraints
                else sketch
                for sketch in result
            }
            context = self._active_execution_context
            if context is not None and context.command_version >= 2:
                self._validate_attached_sketch_changes(sketches)
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        previous_sketches = self._sketches
        self._sketches = candidate._sketches
        self._associative_arrays = {array.array_id: array for array in arrays}
        self._record_sketch_change(
            command_id,
            previous_sketches=previous_sketches
            if context is not None and context.command_version >= 2
            else None,
        )

    def _set_array_member_offsets(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.offset"
        try:
            from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

            offsets: dict[ArrayEntityRef, tuple[float, float]] = {}
            for raw in cast("Sequence[Mapping[str, object]]", params.get("members", ())):
                target = ArrayEntityRef.from_mapping(raw["target"])
                if target in offsets:
                    raise ValueError("阵列成员偏移引用重复。")
                point = cast("Sequence[float]", raw["offset_mm"])
                offsets[target] = (point[0], point[1])
            context = self._active_execution_context
            if context is not None and context.command_version < 2:
                arrays = tuple(
                    array
                    for array in self.associative_arrays
                    if array.array_id == params["array_id"]
                )
                if any(
                    output.target in offsets
                    or (params.get("reset_all") is True and output.offset_mm != (0.0, 0.0))
                    for array in arrays
                    for output in array.extra_outputs
                ):
                    raise ValueError("此偏移命令版本不能修改额外输出。")
            result, updated = set_array_member_offsets(
                tuple(self._sketches.values()),
                self.associative_arrays,
                cast("str", params["array_id"]),
                offsets,
                reset_all=params.get("reset_all") is True,
            )
            sketches = {
                sketch.sketch_id: validate_sketch_revision_geometry(
                    self._sketches[sketch.sketch_id], sketch
                )
                if sketch != self._sketches[sketch.sketch_id] and sketch.constraints
                else sketch
                for sketch in result
            }
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(command_id)

    def _set_array_member_rotations(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.rotate"
        try:
            from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

            rotations: dict[ArrayEntityRef, tuple[float, tuple[float, float]]] = {}
            for raw in cast("Sequence[Mapping[str, object]]", params["members"]):
                target = ArrayEntityRef.from_mapping(raw["target"])
                if target in rotations:
                    raise ValueError("阵列成员旋转引用重复。")
                center = cast("Sequence[float]", raw["center_offset_mm"])
                rotations[target] = (cast("float", raw["angle_deg"]), (center[0], center[1]))
            context = self._active_execution_context
            if (
                context is not None
                and context.command_version < 2
                and any(
                    output.target in rotations
                    for array in self.associative_arrays
                    if array.array_id == params["array_id"]
                    for output in array.extra_outputs
                )
            ):
                raise ValueError("此旋转命令版本不能修改额外输出。")
            result, updated = set_array_member_rotations(
                tuple(self._sketches.values()),
                self.associative_arrays,
                cast("str", params["array_id"]),
                rotations,
            )
            sketches = {
                sketch.sketch_id: validate_sketch_revision_geometry(
                    self._sketches[sketch.sketch_id], sketch
                )
                if sketch != self._sketches[sketch.sketch_id] and sketch.constraints
                else sketch
                for sketch in result
            }
            if context is not None and context.command_version >= 3:
                self._validate_attached_sketch_changes(sketches)
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        previous_sketches = self._sketches
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(
            command_id,
            previous_sketches=previous_sketches
            if context is not None and context.command_version >= 3
            else None,
        )

    def _reset_array_member_overrides(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.reset"
        try:
            from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

            context = self._active_execution_context
            if (
                context is not None
                and context.command_version < 4
                and any(
                    array.extra_outputs
                    for array in self.associative_arrays
                    if array.array_id == params["array_id"]
                )
            ):
                raise ValueError("此重置版本不能清除额外输出。")
            if (
                context is not None
                and context.command_version < 3
                and any(
                    member.replacement is not None
                    for array in self.associative_arrays
                    if array.array_id == params["array_id"]
                    for member in array.members
                )
            ):
                raise ValueError("此重置版本不能清除成员替换。")
            if (
                context is not None
                and context.command_version == 1
                and any(
                    member.erased_index is not None
                    for array in self.associative_arrays
                    if array.array_id == params["array_id"]
                    for member in array.members
                )
            ):
                raise ValueError("此重置版本不能恢复已擦除成员。")
            if context is not None and context.command_version >= 5:
                replaced = {
                    member.target
                    for array in self.associative_arrays
                    if array.array_id == params["array_id"]
                    for member in array.members
                    if member.replacement is not None
                }
                self._reject_attached_array_replacements(replaced)
            result, updated = reset_array_member_overrides(
                tuple(self._sketches.values()),
                self.associative_arrays,
                cast("str", params["array_id"]),
            )
            sketches = {
                sketch.sketch_id: validate_sketch_revision_geometry(
                    self._sketches[sketch.sketch_id], sketch
                )
                if sketch != self._sketches[sketch.sketch_id] and sketch.constraints
                else sketch
                for sketch in result
            }
            if context is not None and context.command_version >= 5:
                for identity, revised in sketches.items():
                    if revised != self._sketches.get(identity):
                        state = revised.to_state_mapping()
                        self.validate_datum_revision(
                            "sketch.revise",
                            {
                                "sketch_id": identity,
                                "entities": state["entities"],
                                "constraints": state["constraints"],
                            },
                        )
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        previous_sketches = self._sketches
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(
            command_id,
            previous_sketches=previous_sketches
            if context is not None and context.command_version >= 5
            else None,
        )

    def _erase_array_members(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.erase"
        try:
            targets = tuple(
                ArrayEntityRef.from_mapping(raw)
                for raw in cast("Sequence[object]", params["targets"])
            )
            context = self._active_execution_context
            if context is not None and context.command_version >= 3 and "array_id" not in params:
                if any(ref.sketch_id in self._linked_sketches for ref in targets):
                    raise ValueError("外部关联草图只读，不能删除图元。")
                member_refs = {
                    member.target for array in self.associative_arrays for member in array.members
                }
                extra_refs = {
                    output.target
                    for array in self.associative_arrays
                    for output in array.extra_outputs
                }
                if context.command_version < 4 and set(targets) & extra_refs:
                    raise ValueError("此删除版本不能删除额外阵列输出。")
                member_refs.update(extra_refs)
                ordinary = set(targets) - member_refs
                relations = {
                    identity: relation
                    for identity, relation in self._cross_tangencies.items()
                    if all(
                        ArrayEntityRef(ref.sketch_id, ref.entity_id) not in ordinary
                        for ref in (relation.first, relation.second)
                    )
                }
                result, arrays = erase_drawing_entities(
                    tuple(self._sketches.values()), self.associative_arrays, targets
                )
                sketches = {sketch.sketch_id: sketch for sketch in result}
                validate_array_cross_changes(
                    self._sketches, sketches, self.associative_arrays, tuple(relations.values())
                )
                self._validate_cross_tangencies(sketches, relations)
                candidate = self._regenerate_with_sketches(sketches)
                self._sketches = candidate._sketches
                self._associative_arrays = {array.array_id: array for array in arrays}
                self._cross_tangencies = relations
                self._record_sketch_change(command_id)
                return
            result, updated = erase_array_members(
                tuple(self._sketches.values()),
                self.associative_arrays,
                cast("str", params["array_id"]),
                targets,
                preserve_order=self._active_execution_context is not None
                and self._active_execution_context.command_version >= 2,
            )
            sketches = {sketch.sketch_id: sketch for sketch in result}
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(command_id)

    def _replace_array_members(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.replace"
        try:
            from mycad.geom.sketch_constraints import validate_sketch_revision_geometry

            replacements: dict[ArrayEntityRef, ArrayReplacement] = {}
            for raw in cast("Sequence[Mapping[str, object]]", params["members"]):
                target = ArrayEntityRef.from_mapping(raw["target"])
                replacement = ArrayReplacement.from_mapping(raw["replacement"])
                if target in replacements:
                    raise ValueError("阵列替换成员引用重复。")
                if replacement.source.sketch_id in self._linked_sketches:
                    raise ValueError("外部关联草图只读，不能作为阵列替换来源。")
                replacements[target] = replacement
            context = self._active_execution_context
            if context is not None and context.command_version >= 9:
                current_array = next(
                    (
                        array
                        for array in self.associative_arrays
                        if array.array_id == params["array_id"]
                    ),
                    None,
                )
                if current_array is not None:
                    changed = {
                        member.target
                        for member in current_array.members
                        if member.target in replacements
                        and member.replacement != replacements[member.target]
                    }
                    self._reject_attached_array_replacements(changed)
            if context is not None and context.command_version < 3:
                candidate_arrays = tuple(
                    replace(
                        array,
                        members=tuple(
                            replace(member, replacement=replacements[member.target])
                            if member.target in replacements
                            else member
                            for member in array.members
                        ),
                    )
                    if array.array_id == params["array_id"]
                    else array
                    for array in self.associative_arrays
                )
                if has_interleaved_array_dependencies(candidate_arrays):
                    raise ValueError("此替换版本不支持交错阵列依赖。")
            if context is not None and context.command_version < 2:
                current = next(
                    (
                        array
                        for array in self.associative_arrays
                        if array.array_id == params["array_id"]
                    ),
                    None,
                )
                if current is not None:
                    targets = {member.target for member in current.members}
                    if has_internal_replacements(current) or any(
                        replacement.source in targets for replacement in replacements.values()
                    ):
                        raise ValueError("此替换版本不支持阵列内部替换依赖。")
            erased = tuple(
                ArrayEntityRef.from_mapping(raw)
                for raw in cast("Sequence[object]", params.get("erase_members", ()))
            )
            extras = tuple(
                ArrayExtraOutput.from_mapping(raw)
                for raw in cast("Sequence[object]", params.get("extra_outputs", ()))
            )
            if erased and extras:
                raise ValueError("不能同时增加和擦除阵列单元输出。")
            if any(
                output.source.sketch_id in self._linked_sketches
                or output.target.sketch_id in self._linked_sketches
                or output.anchor_source.sketch_id in self._linked_sketches
                for output in extras
            ):
                raise ValueError("外部关联草图只读，不能参与额外输出。")
            if extras:
                result, updated = replace_array_cell_with_extra_outputs(
                    tuple(self._sketches.values()),
                    self.associative_arrays,
                    cast("str", params["array_id"]),
                    replacements,
                    extras,
                )
            elif erased:
                result, updated = replace_and_erase_array_members(
                    tuple(self._sketches.values()),
                    self.associative_arrays,
                    cast("str", params["array_id"]),
                    replacements,
                    erased,
                )
            else:
                result, updated = set_array_member_replacements(
                    tuple(self._sketches.values()),
                    self.associative_arrays,
                    cast("str", params["array_id"]),
                    replacements,
                )
            sketches = {
                sketch.sketch_id: validate_sketch_revision_geometry(
                    self._sketches[sketch.sketch_id], sketch
                )
                if sketch != self._sketches[sketch.sketch_id] and sketch.constraints
                else sketch
                for sketch in result
            }
            if context is not None and context.command_version >= 9:
                self._validate_attached_sketch_changes(sketches)
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        previous_sketches = self._sketches
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(
            command_id,
            previous_sketches=previous_sketches
            if context is not None and context.command_version >= 9
            else None,
        )

    def _apply_associative_array(self, params: Mapping[str, object]) -> None:
        command_id = "drawing.array.add"
        try:
            array = AssociativeRectArray.from_mapping(params.get("array"))
            self._validate_associative_array(array, self._sketches, self._associative_arrays)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._associative_arrays = {**self._associative_arrays, array.array_id: array}
        self._record_sketch_change(command_id)

    def _validate_associative_array(
        self,
        array: AssociativeRectArray,
        sketches: Mapping[str, Sketch],
        arrays: Mapping[str, AssociativeRectArray],
    ) -> None:
        if array.array_id in arrays:
            raise ValueError("关联阵列身份已存在。")
        context = self._active_execution_context
        minimum_versions = {
            "sketch.create": 21,
            "drawing.sketch.revise": 18,
            "drawing.array.add": 9,
        }
        interleaved_versions = {
            "sketch.create": 22,
            "drawing.sketch.revise": 19,
            "drawing.array.add": 10,
        }
        if (
            context is not None
            and context.command_id in interleaved_versions
            and (
                context.command_version < interleaved_versions[context.command_id]
                and has_interleaved_array_dependencies((*arrays.values(), array))
            )
        ):
            raise ValueError("此命令版本不支持交错阵列依赖。")
        if (
            context is not None
            and context.command_id in minimum_versions
            and (
                context.command_version < minimum_versions[context.command_id]
                and has_internal_replacements(array)
            )
        ):
            raise ValueError("此命令版本不支持阵列内部替换依赖。")
        refs = (
            *array.sources,
            *(member.target for member in array.members),
            *(
                member.replacement.source
                for member in array.members
                if member.replacement is not None
            ),
            *(
                ref
                for output in array.extra_outputs
                for ref in (output.source, output.target, output.anchor_source)
            ),
        )
        erased = {member.target for member in array.members if member.erased_index is not None}
        if any(ref.sketch_id in self._linked_sketches for ref in refs):
            raise ValueError("外部关联草图只读，不能参与关联阵列。")
        entities = {
            (sketch.sketch_id, entity.entity_id): entity
            for sketch in sketches.values()
            for entity in sketch.entities
        }
        for ref in refs:
            sketch = sketches.get(ref.sketch_id)
            if sketch is None:
                raise ValueError("关联阵列引用的草图不存在。")
            entity = entities.get((ref.sketch_id, ref.entity_id))
            if ref in erased:
                if entity is not None:
                    raise ValueError("已擦除阵列副本的身份被占用。")
                continue
            if entity is None:
                raise ValueError("关联阵列引用的图元不存在。")
            layer = sketch.layers.get(entity.layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError("关联阵列图元位于锁定或隐藏图层。")
        values = (*arrays.values(), array)
        states = tuple(sketches.values())
        propagate_array_changes(states, states, values)

    def _prove_array_reorder_tangencies(
        self,
        edges: tuple[tuple[ArrayEntityRef, ArrayEntityRef], ...],
        proofs: tuple[Sketch, ...] | None,
        mappings: Mapping[tuple[str, str], PolylineTopologyMap],
        input_mappings: Mapping[tuple[str, str], PolylineTopologyMap],
        relations: Mapping[str, CrossSketchTangency],
        proposed: Mapping[str, Sketch],
        command_id: str,
        *,
        allow_reversed_segments: bool = False,
        allow_partial_rebindings: bool = False,
    ) -> tuple[
        frozenset[tuple[str, str]], tuple[CrossSketchTangency, ...], tuple[CrossSketchTangency, ...]
    ]:
        if proofs is None:
            return frozenset(), (), ()
        keys = frozenset((target.sketch_id, target.entity_id) for _source, target in edges)
        original = tuple(
            item
            for item in self.cross_sketch_tangencies
            if any((ref.sketch_id, ref.entity_id) in keys for ref in (item.first, item.second))
        )
        try:
            changed = tuple(item for item in original if relations.get(item.relation_id) != item)
            if changed:
                if not allow_partial_rebindings:
                    raise ValueError("不能同时改写阵列成员的相切关系。")
                expected = rebind_proven_array_tangencies(
                    tuple(self._sketches.values()),
                    tuple(proposed.values()),
                    changed,
                    input_mappings,
                    allow_reversed_segments=allow_reversed_segments,
                )
                if any(relations.get(item.relation_id) != item for item in expected):
                    raise ValueError("阵列来源相切重绑定与修订前后几何不一致。")
            rebound = (
                rebind_proven_array_tangencies(
                    tuple(self._sketches.values()),
                    proofs,
                    original,
                    mappings,
                    allow_reversed_segments=allow_reversed_segments,
                )
                if original
                else ()
            )
            targets = frozenset(
                (ref.sketch_id, ref.entity_id)
                for item in original
                for ref in (item.first, item.second)
                if (ref.sketch_id, ref.entity_id) in keys
            )
            return targets, original, rebound
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"阵列成员相切证明失败：{exc}", command_id=command_id) from exc

    def _finalize_array_reorder_tangencies(
        self,
        original: tuple[CrossSketchTangency, ...],
        predicted: tuple[CrossSketchTangency, ...],
        sketches: Mapping[str, Sketch],
        mappings: Mapping[tuple[str, str], PolylineTopologyMap],
        relations: dict[str, CrossSketchTangency],
        command_id: str,
        *,
        allow_reversed_segments: bool = False,
    ) -> set[str]:
        if not original:
            return set()
        try:
            actual = rebind_proven_array_tangencies(
                tuple(self._sketches.values()),
                tuple(sketches.values()),
                original,
                mappings,
                allow_reversed_segments=allow_reversed_segments,
            )
            if actual != predicted:
                raise ValueError("阵列成员相切实际结果与候选证明不一致。")
            for item in actual:
                relations[item.relation_id] = item
            return {item.relation_id for item in actual}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"阵列成员相切重绑定失败：{exc}", command_id=command_id) from exc

    def _apply_sketch_revisions(
        self,
        revisions: Sequence[Mapping[str, object]],
        *,
        command_id: str,
        relation: CrossSketchTangency | None = None,
        additions: Sequence[CrossSketchTangency] = (),
        removals: Sequence[str] = (),
        array_additions: Sequence[AssociativeRectArray] = (),
        record: bool = True,
        dimension: Mapping[str, object] | None = None,
        erased_members: Sequence[ArrayEntityRef] = (),
        rectangle_transforms: Sequence[RectangleTransformEvidence] = (),
        polyline_transforms: Sequence[RectangleTransformEvidence] = (),
        line_transforms: Sequence[RectangleTransformEvidence] = (),
        topology_records: Sequence[Mapping[str, object]] = (),
        verified_exact: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        """Validate a complete candidate before installing any sketch or relation."""
        dimension_sketch = dimension.get("sketch_id") if dimension is not None else None
        dimension_constraint = (
            SketchConstraint.from_mapping(dimension.get("constraint"))
            if dimension is not None
            else None
        )
        if (
            dimension is not None
            and sum(revision.get("sketch_id") == dimension_sketch for revision in revisions) != 1
        ):
            raise ValidationError("dimension target must have one revision", command_id=command_id)
        prepared = tuple(
            self._prepare_sketch_revision(
                revision,
                dimension=dimension_constraint
                if revision.get("sketch_id") == dimension_sketch
                else None,
                rectangle_transforms=rectangle_transforms,
                verified_exact=verified_exact,
            )
            for revision in revisions
        )
        mapped_datums = tuple(self._datum_identifiers.values())
        mapped_frames = tuple(self._tolerance_frames.values())
        exact_reorder_annotations: set[tuple[str, str]] = set()
        array_reorder_members: tuple[tuple[ArrayEntityRef, ArrayEntityRef], ...] = ()
        chain_policy_used = False
        chain_proofs: tuple[Sketch, ...] | None = None
        chain_maps: dict[tuple[str, str], PolylineTopologyMap] = {}
        rebound_arrays: tuple[AssociativeRectArray, ...] | None = None
        input_maps: dict[tuple[str, str], PolylineTopologyMap] = {}
        if topology_records:
            try:
                stable_anchors: set[tuple[str, str]] = set()
                for revised in prepared:
                    current = self._sketches[revised.sketch_id]
                    revised_entities = {item.entity_id: item for item in revised.entities}
                    for old in current.entities:
                        key = (current.sketch_id, old.entity_id)
                        new = revised_entities.get(old.entity_id)
                        if (
                            key in verified_exact
                            and isinstance(old, PolylineEntity)
                            and isinstance(new, PolylineEntity)
                            and old.points_mm[0] == new.points_mm[0]
                        ):
                            stable_anchors.add(key)
                input_maps = {
                    (cast("str", record["sketch_id"]), mapping.entity_id): mapping
                    for record in topology_records
                    for mapping in (PolylineTopologyMap.from_mapping(record["mapping"]),)
                }
                prepared_by_id = {item.sketch_id: item for item in prepared}
                before_sketches = tuple(self._sketches.values())
                after_sketches = tuple(
                    prepared_by_id.get(item.sketch_id, item) for item in before_sketches
                )
                stable_bases = stable_array_base_ids(
                    self.associative_arrays, before_sketches, after_sketches, input_maps
                )
                context = self._active_execution_context
                if context is not None and context.command_version >= 58:
                    rebound_base_arrays: list[AssociativeRectArray] = []
                    changed_bases: set[str] = set()
                    for array in self.associative_arrays:
                        base = array.base_point
                        if base is None or base.source is None:
                            rebound_base_arrays.append(array)
                            continue
                        key = (base.source.sketch_id, base.source.entity_id)
                        mapping = input_maps.get(key)
                        if mapping is None:
                            rebound_base_arrays.append(array)
                            continue
                        before_sketch = self._sketches[key[0]]
                        after_sketch = prepared_by_id.get(key[0], before_sketch)
                        changed = rebind_array_base(array, before_sketch, after_sketch, mapping)
                        rebound_base_arrays.append(changed)
                        if changed != array:
                            changed_bases.add(array.array_id)
                    if changed_bases:
                        rebound_arrays = tuple(rebound_base_arrays)
                        stable_bases = stable_bases | frozenset(changed_bases)
                try:
                    array_reorder_members = simple_array_reorder_members(
                        self.associative_arrays,
                        verified_exact,
                        stable_anchor_sources=frozenset(stable_anchors),
                        stable_base_arrays=stable_bases,
                        allow_stable_replacements=(
                            context is not None and context.command_version >= 59
                        ),
                        allow_stable_extra_outputs=(
                            context is not None and context.command_version >= 60
                        ),
                        allow_reordered_extra_outputs=(
                            context is not None and context.command_version >= 61
                        ),
                        allow_independent_extra_sources=(
                            context is not None and context.command_version >= 62
                        ),
                        allow_replacement_source=(
                            context is not None and context.command_version >= 65
                        ),
                    )
                    if (
                        context is not None
                        and context.command_version >= 75
                        and (
                            context.command_version >= 77
                            or has_internal_reorder_dependents(
                                self.associative_arrays, array_reorder_members
                            )
                        )
                    ):
                        raise ValueError("阵列内部来源需要逐层证明。")
                except ValueError:
                    if context is None or context.command_version < 66:
                        raise
                    array_reorder_members = simple_array_reorder_chain(
                        self.associative_arrays,
                        verified_exact,
                        stable_anchor_sources=(
                            frozenset(stable_anchors)
                            if context.command_version >= 67
                            else frozenset()
                        ),
                        allow_stable_bases=context.command_version >= 68,
                        stable_base_vertices=(
                            {
                                key: frozenset(
                                    index
                                    for index, new_index in enumerate(mapping.old_to_new)
                                    if index == new_index
                                )
                                for key, mapping in input_maps.items()
                            }
                            if context.command_version >= 69
                            else None
                        ),
                        allow_base_rebinding=context.command_version >= 70,
                        allow_unchanged_replacements=context.command_version >= 71,
                        allow_reordered_replacements=context.command_version >= 72,
                        allow_extra_outputs=context.command_version >= 73,
                        allow_simultaneous_replacements=context.command_version >= 74,
                        defer_affected_dependencies=context.command_version >= 75,
                        allow_mixed_replacement_extras=context.command_version >= 76,
                        known_stable_base_arrays=(
                            stable_bases if context.command_version >= 75 else frozenset()
                        ),
                    )
                    chain_policy_used = True
                    if context.command_version >= 70:
                        proposed_by_id = {item.sketch_id: item for item in prepared}
                        originals = tuple(self._sketches.values())
                        proposed = tuple(
                            proposed_by_id.get(item.sketch_id, item) for item in originals
                        )
                        chain_proofs, chain_maps = predict_chain_reorder(
                            originals,
                            proposed,
                            self.associative_arrays,
                            array_reorder_members,
                            input_maps,
                            allow_unchanged_replacements=context.command_version >= 71,
                            allow_reordered_replacements=context.command_version >= 72,
                            allow_extra_outputs=context.command_version >= 73,
                        )
                        proof_by_id = {item.sketch_id: item for item in chain_proofs}
                        rebound_chain_arrays: list[AssociativeRectArray] = []
                        for array in self.associative_arrays:
                            base = array.base_point
                            if base is None or base.source is None:
                                rebound_chain_arrays.append(array)
                                continue
                            key = (base.source.sketch_id, base.source.entity_id)
                            mapping = chain_maps.get(key)
                            rebound_chain_arrays.append(
                                rebind_array_base(
                                    array, self._sketches[key[0]], proof_by_id[key[0]], mapping
                                )
                                if mapping is not None
                                else array
                            )
                        rebound_arrays = tuple(rebound_chain_arrays)
            except ValueError as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            for revised in prepared:
                current = self._sketches[revised.sketch_id]
                try:
                    validate_topology_constraint_rebinding(
                        current,
                        revised,
                        frozenset(
                            entity_id
                            for sketch_id, entity_id in verified_exact
                            if sketch_id == current.sketch_id
                        ),
                    )
                except ValueError as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
                maps = tuple(
                    PolylineTopologyMap.from_mapping(record["mapping"])
                    for record in topology_records
                    if record["sketch_id"] == revised.sketch_id
                )
                if not maps:
                    continue
                try:
                    next_datums, next_frames = remap_annotations(
                        current, revised, maps, mapped_datums, mapped_frames
                    )
                    for before, after in zip(mapped_datums, next_datums, strict=True):
                        if (
                            before.attachment is not None
                            and (before.attachment.sketch_id, before.attachment.reference.entity_id)
                            in verified_exact
                        ):
                            exact_reorder_annotations.add(("datum", before.datum_id))
                        if before != after:
                            layer = self.drawing_layers.get(before.layer_name)
                            if layer.locked or layer.frozen:
                                raise ValueError("锁定或冻结图层上的基准不能修改。")
                    for before, after in zip(mapped_frames, next_frames, strict=True):
                        if (
                            before.leader_attachment is not None
                            and (
                                before.leader_attachment.sketch_id,
                                before.leader_attachment.reference.entity_id,
                            )
                            in verified_exact
                        ):
                            exact_reorder_annotations.add(("frame", before.frame_id))
                        if before != after:
                            layer = self.drawing_layers.get(before.layer_name)
                            if layer.locked or layer.frozen:
                                raise ValueError("锁定或冻结图层上的公差框不能修改。")
                    mapped_datums, mapped_frames = next_datums, next_frames
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
        if dimension is not None and any(
            sketch.sketch_id != dimension_sketch
            and (
                len(sketch.constraints) != len(self._sketches[sketch.sketch_id].constraints)
                or any(
                    before != after and not is_reference_value_refresh(before, after)
                    for before, after in zip(
                        self._sketches[sketch.sketch_id].constraints,
                        sketch.constraints,
                        strict=True,
                    )
                )
            )
            for sketch in prepared
        ):
            raise ValidationError(
                "dimension revision changed another constraint", command_id=command_id
            )
        ids = tuple(sketch.sketch_id for sketch in prepared)
        if len(set(ids)) != len(ids):
            raise ValidationError("duplicate sketch revision", command_id=command_id)
        relations = dict(self._cross_tangencies)
        if dimension is not None:
            try:
                if not isinstance(dimension_sketch, str):
                    raise ValueError("dimension target is invalid")
                component, selected = resolve_tangency_component(
                    tuple(self._sketches.values()), tuple(relations.values()), dimension_sketch
                )
                local_tangency = (
                    dimension_constraint is not None
                    and dimension_constraint.kind == "tangent"
                    and self._active_execution_context is not None
                    and self._active_execution_context.command_id == "drawing.sketch.revise"
                    and self._active_execution_context.command_version >= 38
                    and not selected
                    and set(ids) == {dimension_sketch}
                )
                if not local_tangency and (
                    not selected or not set(ids).issubset({item.sketch_id for item in component})
                ):
                    raise ValueError("dimension revision includes an unrelated sketch")
            except (KeyError, ValueError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
        if len(set(removals)) != len(removals) or any(
            identity not in relations for identity in removals
        ):
            raise ValidationError("待移除的相切关系不存在或重复。", command_id=command_id)
        for identity in removals:
            del relations[identity]
        for new_relation in (*additions, *((relation,) if relation is not None else ())):
            if new_relation.relation_id in relations:
                raise ValidationError("相切关系身份已存在。", command_id=command_id)
            if (
                new_relation.first.sketch_id in self._linked_sketches
                or new_relation.second.sketch_id in self._linked_sketches
            ):
                raise ValidationError("关联草图只读，不能添加跨草图相切。", command_id=command_id)
            relations[new_relation.relation_id] = new_relation
        sketches = {**self._sketches, **{sketch.sketch_id: sketch for sketch in prepared}}
        context = self._active_execution_context
        new_relations = (*additions, *((relation,) if relation is not None else ()))
        if (
            context is not None
            and not (
                (context.command_id == "drawing.sketch.revise" and context.command_version >= 27)
                or (context.command_id == "drawing.tangency.add" and context.command_version >= 6)
            )
            and relations_use_rectangle_segments(tuple(sketches.values()), new_relations)
        ):
            raise ValidationError("矩形边相切关系需要新版修订命令。", command_id=command_id)
        arrays = dict(self._associative_arrays)
        proven_reorder_targets, original_proven_tangencies, proven_tangencies = (
            self._prove_array_reorder_tangencies(
                array_reorder_members,
                chain_proofs if context is not None and context.command_version >= 77 else None,
                chain_maps,
                input_maps,
                relations,
                sketches,
                command_id,
                allow_reversed_segments=context is not None and context.command_version >= 78,
                allow_partial_rebindings=context is not None and context.command_version >= 79,
            )
        )
        if erased_members:
            try:
                available = {
                    member.target
                    for array in self.associative_arrays
                    for member in array.members
                    if member.erased_index is None
                }
                context = self._active_execution_context
                if context is not None and context.command_version >= 23:
                    available.update(
                        output.target
                        for array in self.associative_arrays
                        for output in array.extra_outputs
                    )
                if not set(erased_members).issubset(available):
                    raise ValueError("擦除引用必须指向现存阵列成员。")
                initial = tuple(self._sketches.values())
                if context is not None and context.command_version >= 26:
                    initial = strip_erased_member_dimensions(
                        initial, prepared, tuple(erased_members)
                    )
                baseline, updated_arrays = erase_drawing_entities(
                    initial, self.associative_arrays, tuple(erased_members)
                )
                if any(
                    any(
                        entity.entity_id == ref.entity_id
                        for entity in sketches[ref.sketch_id].entities
                    )
                    for ref in erased_members
                ):
                    raise ValueError("擦除的阵列成员仍存在于草图修订中。")
                result = propagate_array_changes(baseline, tuple(sketches.values()), updated_arrays)
                sketches = {sketch.sketch_id: sketch for sketch in result}
                deleted_ordinary = {
                    ArrayEntityRef(sketch.sketch_id, entity.entity_id)
                    for sketch in self._sketches.values()
                    for entity in sketch.entities
                    if ArrayEntityRef(sketch.sketch_id, entity.entity_id) not in erased_members
                    and all(
                        current.entity_id != entity.entity_id
                        for current in sketches[sketch.sketch_id].entities
                    )
                }
                protected_relations = {
                    identity: relation
                    for identity, relation in self._cross_tangencies.items()
                    if all(
                        ArrayEntityRef(ref.sketch_id, ref.entity_id) not in deleted_ordinary
                        for ref in (relation.first, relation.second)
                    )
                }
                protected_relations.update(relations)
                validate_array_cross_changes(
                    self._sketches,
                    sketches,
                    self.associative_arrays,
                    tuple(protected_relations.values()),
                )
                arrays = {array.array_id: array for array in updated_arrays}
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
        else:
            sketches = self._propagate_associative_arrays(
                sketches,
                command_id,
                resulting_arrays=rebound_arrays,
                base_rebind_maps=(chain_maps or input_maps) if rebound_arrays is not None else None,
                base_rebind_proofs=chain_proofs,
                proven_reorder_targets=proven_reorder_targets,
            )
            if rebound_arrays is not None:
                arrays = {array.array_id: array for array in rebound_arrays}
        if topology_records and array_reorder_members:
            source_maps = {
                (cast("str", record["sketch_id"]), mapping.entity_id): mapping
                for record in topology_records
                for mapping in (PolylineTopologyMap.from_mapping(record["mapping"]),)
            }
            target_groups: dict[str, list[PolylineTopologyMap]] = {}
            extra_targets = {
                (output.target.sketch_id, output.target.entity_id)
                for array in self.associative_arrays
                for output in array.extra_outputs
            }
            extra_sources = {
                (output.target.sketch_id, output.target.entity_id): output.source
                for array in self.associative_arrays
                for output in array.extra_outputs
            }
            relation_targets = associative_topology_entities((), self.cross_sketch_tangencies)
            try:
                for source_ref, target_ref in array_reorder_members:
                    source_key = (source_ref.sketch_id, source_ref.entity_id)
                    target_key = (target_ref.sketch_id, target_ref.entity_id)
                    old_sketch = self._sketches[target_ref.sketch_id]
                    new_sketch = sketches[target_ref.sketch_id]
                    old = next(
                        item
                        for item in old_sketch.entities
                        if item.entity_id == target_ref.entity_id
                    )
                    new = next(
                        item
                        for item in new_sketch.entities
                        if item.entity_id == target_ref.entity_id
                    )
                    if context is not None and context.command_version >= 59 and old == new:
                        continue
                    if target_key in extra_targets and (
                        context is None
                        or context.command_version < 61
                        or source_key
                        not in (source_maps if context.command_version >= 73 else input_maps)
                        or (
                            context.command_version >= 62
                            and extra_sources[target_key] != source_ref
                        )
                    ):
                        raise ValueError("阵列额外输出几何发生变化，需要单独重绑定。")
                    if target_key in relation_targets and target_key not in proven_reorder_targets:
                        raise ValueError("阵列成员的相切关系需要单独重绑定。")
                    if not isinstance(old, PolylineEntity) or not isinstance(new, PolylineEntity):
                        raise ValueError("阵列成员不是同一多段线。")
                    source_map = source_maps[source_key]
                    target_map = PolylineTopologyMap(
                        target_ref.entity_id, source_map.old_to_new, len(new.points_mm), new.closed
                    )
                    if old.point_ids:
                        if new.point_ids != old.point_ids or len(old.point_ids) != len(
                            target_map.old_to_new
                        ):
                            raise ValueError("阵列成员点身份在传播中意外改变。")
                        ordered_ids: list[str | None] = [None] * len(new.points_mm)
                        for old_index, new_index in enumerate(target_map.old_to_new):
                            if new_index is None:
                                raise ValueError("阵列成员拓扑映射缺少点身份。")
                            ordered_ids[new_index] = old.point_ids[old_index]
                        if any(identity is None for identity in ordered_ids):
                            raise ValueError("阵列成员拓扑映射缺少点身份。")
                        new = replace(new, point_ids=tuple(cast("Sequence[str]", ordered_ids)))
                    target_map.validate_exact_reorder(old, new)
                    if new != next(
                        item
                        for item in new_sketch.entities
                        if item.entity_id == target_ref.entity_id
                    ):
                        new_sketch = replace(
                            new_sketch,
                            entities=tuple(
                                new if item.entity_id == target_ref.entity_id else item
                                for item in new_sketch.entities
                            ),
                        )
                        sketches[target_ref.sketch_id] = new_sketch
                    target_groups.setdefault(target_ref.sketch_id, []).append(target_map)
                    source_maps[target_key] = target_map
                if context is not None and 68 <= context.command_version < 70 and chain_policy_used:
                    stable = stable_array_base_ids(
                        self.associative_arrays,
                        tuple(self._sketches.values()),
                        tuple(sketches.values()),
                        source_maps,
                    )
                    for array in self.associative_arrays:
                        base = array.base_point
                        if (
                            base is not None
                            and base.source is not None
                            and (base.source.sketch_id, base.source.entity_id) in source_maps
                            and array.array_id not in stable
                        ):
                            raise ValueError("链式阵列基点未能证明保持不变。")
                if chain_proofs is not None:
                    proof_by_id = {item.sketch_id: item for item in chain_proofs}
                    for _source, target in array_reorder_members:
                        actual = next(
                            item
                            for item in sketches[target.sketch_id].entities
                            if item.entity_id == target.entity_id
                        )
                        proof = next(
                            item
                            for item in proof_by_id[target.sketch_id].entities
                            if item.entity_id == target.entity_id
                        )
                        if actual != proof:
                            raise ValueError("链式阵列传播结果与基点证明不一致。")
                for sketch_id, maps in target_groups.items():
                    old_sketch, new_sketch = self._sketches[sketch_id], sketches[sketch_id]
                    validate_topology_constraint_rebinding(
                        old_sketch, new_sketch, frozenset(item.entity_id for item in maps)
                    )
                    next_datums, next_frames = remap_annotations(
                        old_sketch, new_sketch, tuple(maps), mapped_datums, mapped_frames
                    )
                    target_ids = {item.entity_id for item in maps}
                    for before, after in zip(mapped_datums, next_datums, strict=True):
                        attachment = before.attachment
                        if (
                            attachment is not None
                            and attachment.sketch_id == sketch_id
                            and attachment.reference.entity_id in target_ids
                        ):
                            exact_reorder_annotations.add(("datum", before.datum_id))
                        if before != after:
                            layer = self.drawing_layers.get(before.layer_name)
                            if layer.locked or layer.frozen:
                                raise ValueError("锁定或冻结图层上的基准不能修改。")
                    for before, after in zip(mapped_frames, next_frames, strict=True):
                        attachment = before.leader_attachment
                        if (
                            attachment is not None
                            and attachment.sketch_id == sketch_id
                            and attachment.reference.entity_id in target_ids
                        ):
                            exact_reorder_annotations.add(("frame", before.frame_id))
                        if before != after:
                            layer = self.drawing_layers.get(before.layer_name)
                            if layer.locked or layer.frozen:
                                raise ValueError("锁定或冻结图层上的公差框不能修改。")
                    mapped_datums, mapped_frames = next_datums, next_frames
                    verified_exact = verified_exact | frozenset(
                        (sketch_id, item.entity_id) for item in maps
                    )
            except (KeyError, StopIteration, TypeError, ValueError) as exc:
                raise ValidationError(f"阵列重排无法验证：{exc}", command_id=command_id) from exc
        context = self._active_execution_context
        protect_attached_geometry = context is not None and (
            (context.command_id == "drawing.sketch.revise" and context.command_version >= 56)
            or (context.command_id == "drawing.tangency.add" and context.command_version >= 12)
        )
        if protect_attached_geometry:
            for identity, revised in sketches.items():
                if revised != self._sketches.get(identity):
                    state = revised.to_state_mapping()
                    self.validate_datum_revision(
                        "sketch.revise",
                        {
                            "sketch_id": identity,
                            "entities": state["entities"],
                            "constraints": state["constraints"],
                        },
                        verified_exact=verified_exact,
                    )
        existing_ids: set[tuple[str, str]] = (
            {
                (sketch.sketch_id, entity.entity_id)
                for sketch in self._sketches.values()
                for entity in sketch.entities
            }
            if array_additions
            else set()
        )
        newly_created: set[tuple[str, str]] = (
            {
                (sketch.sketch_id, entity.entity_id)
                for sketch in prepared
                for entity in sketch.entities
                if (sketch.sketch_id, entity.entity_id) not in existing_ids
            }
            if array_additions
            else set()
        )
        try:
            for array in array_additions:
                if any(
                    (ref.sketch_id, ref.entity_id) not in newly_created
                    for ref in (
                        *[member.target for member in array.members],
                        *[output.target for output in array.extra_outputs],
                    )
                ):
                    raise ValueError("新增关联阵列副本必须由本次修订创建。")
                self._validate_associative_array(array, sketches, arrays)
                arrays[array.array_id] = array
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        verified_transform_relations = self._finalize_array_reorder_tangencies(
            original_proven_tangencies,
            proven_tangencies,
            sketches,
            chain_maps,
            relations,
            command_id,
            allow_reversed_segments=context is not None and context.command_version >= 78,
        )
        if rectangle_transforms or polyline_transforms or line_transforms:
            try:
                keys = {
                    (item.reference.sketch_id, item.reference.entity_id)
                    for item in (*rectangle_transforms, *polyline_transforms, *line_transforms)
                }
                if len(keys) != sum(
                    map(len, (rectangle_transforms, polyline_transforms, line_transforms))
                ) or any(sketch_id not in ids for sketch_id, _entity_id in keys):
                    raise ValueError("矩形变换依据重复或草图未修订。")
                affected = tuple(
                    item
                    for item in self._cross_tangencies.values()
                    if any(
                        (ref.sketch_id, ref.entity_id) in keys for ref in (item.first, item.second)
                    )
                )
                context = self._active_execution_context
                referenced = _validate_transform_evidence_references(
                    keys, affected, tuple(self._sketches.values()), rectangle_transforms, context
                )
                polyline_keys = {
                    (item.reference.sketch_id, item.reference.entity_id)
                    for item in (*polyline_transforms, *line_transforms)
                }
                if not polyline_keys.issubset(referenced):
                    raise ValueError("多段线变换依据没有关联的相切关系。")
                rebound = rebind_committed_tangencies(
                    tuple(self._sketches.values()),
                    tuple(sketches.values()),
                    affected,
                    tuple(rectangle_transforms),
                    tuple(polyline_transforms),
                    tuple(line_transforms),
                    adaptive_rectangle_tolerance=bool(
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 81
                    ),
                    allow_extended_segments=bool(
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 35
                    ),
                    allow_extended_arcs=bool(
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 36
                    ),
                    allow_retained_tangent_arcs=bool(
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 37
                    ),
                    allow_retained_tangent_lines=bool(
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 40
                    ),
                    allow_retained_tangent_fragments=bool(
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 43
                    ),
                    allow_split_line_fragments=bool(
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 44
                    ),
                    allow_split_arc_fragments=bool(
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 46
                    ),
                )
                for before, after in zip(affected, rebound, strict=True):
                    if relations.get(before.relation_id) != after:
                        raise ValueError("矩形变换后的相切关系与依据不一致。")
                    verified_transform_relations.add(before.relation_id)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
        for identity, old_relation in self._cross_tangencies.items():
            if identity not in relations:
                continue
            if identity in verified_transform_relations:
                continue
            replacement = relations[identity]
            references = zip(
                (old_relation.first, old_relation.second),
                (replacement.first, replacement.second),
                strict=True,
            )
            for reference, revised_reference in references:
                if reference.entity_id != revised_reference.entity_id:
                    if not (
                        context is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 43
                        and identity in removals
                        and reference.sketch_id in ids
                        and replace(
                            replacement, first=old_relation.first, second=old_relation.second
                        )
                        == old_relation
                        and (
                            unique_retained_relation_fragment(
                                tuple(self._sketches.values()),
                                tuple(sketches.values()),
                                old_relation,
                                reference,
                            )
                            == revised_reference
                            or context.command_version >= 44
                            and unique_split_line_relation_fragment(
                                tuple(self._sketches.values()),
                                tuple(sketches.values()),
                                old_relation,
                                reference,
                            )
                            == revised_reference
                            or context.command_version >= 46
                            and unique_split_arc_relation_fragment(
                                tuple(self._sketches.values()),
                                tuple(sketches.values()),
                                old_relation,
                                reference,
                            )
                            == revised_reference
                        )
                    ):
                        raise ValidationError("相切片段重绑定无效。", command_id=command_id)
                    continue
                if reference != revised_reference and (
                    identity not in removals
                    or replace(replacement, first=old_relation.first, second=old_relation.second)
                    != old_relation
                    or reference.sketch_id != revised_reference.sketch_id
                    or reference.entity_id != revised_reference.entity_id
                    or reference.segment_index is None
                    or revised_reference.segment_index is None
                    or reference.sketch_id not in ids
                ):
                    raise ValidationError("跨草图相切重绑定无效。", command_id=command_id)
                if reference.segment_index is None or reference.sketch_id not in ids:
                    continue
                previous = next(
                    (
                        e
                        for e in self._sketches[reference.sketch_id].entities
                        if e.entity_id == reference.entity_id
                    ),
                    None,
                )
                updated = next(
                    (
                        e
                        for e in sketches[reference.sketch_id].entities
                        if e.entity_id == reference.entity_id
                    ),
                    None,
                )
                if isinstance(previous, RectangleEntity) and isinstance(updated, RectangleEntity):
                    if reference != revised_reference or any(
                        (previous.opposite_corner_mm[axis] - previous.first_corner_mm[axis])
                        * (updated.opposite_corner_mm[axis] - updated.first_corner_mm[axis])
                        <= 0
                        for axis in (0, 1)
                    ):
                        raise ValidationError(
                            "矩形边方向变化，无法保留相切关系。", command_id=command_id
                        )
                    continue
                if not isinstance(previous, PolylineEntity) or not isinstance(
                    updated, PolylineEntity
                ):
                    raise ValidationError("跨草图相切引用的多段线已删除。", command_id=command_id)
                index = reference.segment_index
                old_arc = bool(previous.bulges) and previous.bulges[index] != 0
                new_arc = (
                    bool(updated.bulges)
                    and index < len(updated.bulges)
                    and updated.bulges[index] != 0
                )
                rotated_index = closed_polyline_vertex_rotation_index(previous, updated, index)
                if (
                    (
                        reference != revised_reference
                        or previous.closed != updated.closed
                        or len(previous.points_mm) != len(updated.points_mm)
                        or old_arc != new_arc
                        or (rotated_index is not None and rotated_index != index)
                    )
                    and unique_unchanged_polyline_segment(previous, updated, index)
                    != revised_reference.segment_index
                    and not (
                        (context := self._active_execution_context) is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 35
                        and unique_extended_polyline_segment(previous, updated, index)
                        == revised_reference.segment_index
                    )
                    and not (
                        (context := self._active_execution_context) is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 36
                        and unique_containing_polyline_arc(previous, updated, index)
                        == revised_reference.segment_index
                    )
                    and not (
                        (context := self._active_execution_context) is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 37
                        and unique_retained_relation_arc(
                            tuple(self._sketches.values()),
                            tuple(sketches.values()),
                            old_relation,
                            reference,
                        )
                        == revised_reference.segment_index
                    )
                    and not (
                        (context := self._active_execution_context) is not None
                        and context.command_id == "drawing.sketch.revise"
                        and context.command_version >= 40
                        and unique_retained_relation_line(
                            tuple(self._sketches.values()),
                            tuple(sketches.values()),
                            old_relation,
                            reference,
                        )
                        == revised_reference.segment_index
                    )
                ):
                    raise ValidationError(
                        "多段线拓扑变化前须先移除其跨草图段相切关系。", command_id=command_id
                    )
        if relation is not None:
            try:
                component, _ = resolve_tangency_component(
                    tuple(sketches.values()), tuple(relations.values()), relation.first.sketch_id
                )
                if not set(ids).issubset({sketch.sketch_id for sketch in component}):
                    raise ValueError("相切候选包含无关草图修订。")
                build_tangency_revisions(
                    tuple(self._sketches[identity] for identity in ids), prepared
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
        self._validate_cross_tangencies(sketches, relations)
        previous_sketches = self._sketches
        if prepared:
            candidate = self._regenerate_with_sketches(sketches)
            self._validate_cross_tangencies(candidate._sketches, relations)
            origins = operation_origins(
                self._part,
                candidate._part,
                self._body_origins,
                f"{command_id}:{len(self._snapshots)}",
                command_id,
                {"revisions": tuple(revisions)},
                rebuild=True,
            )
            self._part = candidate._part
            self._design_faces = candidate._design_faces
            self._sketches = candidate._sketches
            self._body_origins = origins
            count = 0 if self._part is None else len(self._part.solids())
            self._body_ids = tuple(self._identity_scope.new_body_id() for _ in range(count))
        self._cross_tangencies = relations
        self._associative_arrays = arrays
        if topology_records:
            self._datum_identifiers = {item.datum_id: item for item in mapped_datums}
            self._tolerance_frames = {item.frame_id: item for item in mapped_frames}
        if record:
            context = self._active_execution_context
            preserve_normal_side = context is not None and (
                (context.command_id == "drawing.sketch.revise" and context.command_version >= 56)
                or (context.command_id == "drawing.tangency.add" and context.command_version >= 12)
            )
            self._record_sketch_change(
                command_id,
                previous_sketches=previous_sketches if preserve_normal_side else None,
                exact_reorder_annotations=exact_reorder_annotations,
            )

    def _apply_cross_tangency(self, params: Mapping[str, object]) -> None:
        try:
            relation = CrossSketchTangency.from_mapping(params.get("relation"))
            revisions = params.get("revisions")
            if not isinstance(revisions, list | tuple):
                raise ValueError("跨草图相切修订必须是数组。")
            values = cast("Sequence[object]", revisions)
            if any(not isinstance(item, Mapping) for item in values):
                raise ValueError("跨草图相切修订必须是数组。")
            context = self._active_execution_context
            if context is not None and context.command_version >= 12:
                self.validate_datum_revision("drawing.sketch.revise", {"revisions": values})
            self._apply_sketch_revisions(
                cast("Sequence[Mapping[str, object]]", values),
                command_id="drawing.tangency.add",
                relation=relation,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id="drawing.tangency.add") from exc

    def _regenerate_with_sketches(self, sketches: Mapping[str, Sketch]) -> BuildKernel:
        """Rebuild consumers from frozen solutions without rerunning a solver.

        Constraint events were already validated against their original states.
        At each sketch's creation point install its current solved local geometry,
        keeping the support frame freshly resolved from the rebuilt upstream solid.
        The candidate stays isolated until every downstream feature succeeds.
        """
        try:
            for identity, revised in sketches.items():
                previous = self._sketches.get(identity)
                if previous is not None:
                    validate_curve_identity_preservation(previous, revised)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        candidate = BuildKernel()
        candidate._reference_loader = self._reference_loader
        candidate.set_drawing_fillet_baseline(self._drawing_fillet_baseline)
        candidate.set_drawing_chamfer_angle_baseline(self._drawing_chamfer_angle_baseline)
        for operation_index, operation in enumerate(self._operations):
            command_id, params = operation.context.command_id, operation.params
            if command_id in (
                "sketch.constraint.add",
                "sketch.constraint.update",
                "sketch.revise",
                "drawing.sketch.revise",
                "drawing.curve_identity.upgrade",
                "drawing.tangency.add",
                "drawing.tangency.remove",
                "drawing.array.add",
                "drawing.array.update",
                "drawing.array.resize",
                "drawing.array.move",
                "drawing.array.batch_override",
                "drawing.array.offset",
                "drawing.array.rotate",
                "drawing.array.reset",
                "drawing.array.erase",
                "drawing.array.replace",
                "drawing.array.remove",
            ):
                continue
            if command_id.startswith(
                (
                    "drawing.text.",
                    "drawing.text_styles.",
                    "drawing.tolerance.",
                    "drawing.reference_dimensions.",
                    "drawing.raster.",
                    "drawing.group.",
                    "drawing.block_library.",
                    "drawing.block.",
                    "drawing.block_instance.",
                )
            ):
                # Text cannot affect solved geometry. The final immutable state is
                # copied below; historical layers may already have been removed.
                if command_id == "drawing.text_styles.set":
                    candidate._drawing_text_styles = TextStyleTable.from_mapping(params)
                elif command_id == "drawing.text.batch" and "styles" in params:
                    candidate._drawing_text_styles = TextStyleTable.from_mapping(params["styles"])
                candidate._drawing_revision += 1
                candidate._snapshots.append(
                    (
                        f"{command_id}:{len(candidate._snapshots)}",
                        candidate._geometry_revision,
                        candidate._part,
                    )
                )
                continue
            if command_id == "drawing.dimension_styles.set":
                # Keep historical style availability for later sketch creation;
                # final sketches already carry the final formatting values.
                candidate._drawing_dimension_styles = DimensionStyleTable.from_mapping(params)
                candidate._record_sketch_change(command_id)
                continue
            if command_id in ("drawing.layers.set", "drawing.clipboard.prepare"):
                # Final sketch solutions already carry final layer assignments.
                # Preserve the history slot without applying an obsolete table.
                if command_id == "drawing.clipboard.prepare":
                    candidate._drawing_dimension_styles = DimensionStyleTable.from_mapping(
                        params["clipboard_styles"]
                    )
                    if "clipboard_text_styles" in params:
                        candidate._drawing_text_styles = TextStyleTable.from_mapping(
                            params["clipboard_text_styles"]
                        )
                candidate._record_sketch_change(command_id)
                continue
            try:
                replay_params = (
                    {
                        key: value
                        for key, value in params.items()
                        if key not in ("cross_tangencies", "associative_arrays", "raster_batch")
                    }
                    if command_id == "sketch.create"
                    else params
                )
                candidate.apply_with_context(command_id, replay_params, operation.context)
            except TopologyReferenceError as exc:
                raise TopologyReferenceError(
                    f"草图下游步骤 {operation_index + 1} 重建失败：{exc.message}",
                    command_id=command_id,
                    ordinal=operation_index,
                    reason=exc.reason,
                    parameter_path=exc.parameter_path,
                ) from exc
            except MycadError as exc:
                raise GeometryBuildError(
                    f"草图下游步骤 {operation_index + 1} 重建失败：{exc.message}",
                    command_id=command_id,
                    ordinal=operation_index,
                ) from exc
            if command_id == "sketch.create":
                sketch_id = params.get("sketch_id")
                if not isinstance(sketch_id, str):
                    raise ValidationError("missing sketch identity during regeneration")
                final = sketches[sketch_id]
                created = candidate._sketches[sketch_id]
                candidate._sketches[sketch_id] = Sketch(
                    final.sketch_id,
                    created.frame,
                    final.entities,
                    constraints=final.constraints,
                    layers=final.layers,
                    support_face=final.support_face,
                )
        candidate._drawing_layers_override = self._drawing_layers_override
        candidate._drawing_rasters = dict(self._drawing_rasters)
        candidate._drawing_groups = self._drawing_groups
        candidate._drawing_block_definitions = self._drawing_block_definitions
        candidate._drawing_block_instances = self._drawing_block_instances
        candidate._drawing_block_library_origins = self._drawing_block_library_origins
        candidate._drawing_texts = dict(self._drawing_texts)
        candidate._drawing_text_styles = self._drawing_text_styles
        candidate._tolerance_frames = dict(self._tolerance_frames)
        candidate._datum_identifiers = dict(self._datum_identifiers)
        candidate._reference_dimensions = dict(self._reference_dimensions)
        candidate._dimension_layer = self._dimension_layer
        candidate._drawing_dimension_styles = self._drawing_dimension_styles
        candidate._drawing_fillet_radius = self._drawing_fillet_radius
        candidate._drawing_chamfer_values = self._drawing_chamfer_values
        candidate._cross_tangencies = dict(self._cross_tangencies)
        candidate._associative_arrays = dict(self._associative_arrays)
        return candidate

    def _record_sketch_change(
        self,
        command_id: str,
        *,
        previous_sketches: Mapping[str, Sketch] | None = None,
        exact_reorder_annotations: set[tuple[str, str]] | None = None,
    ) -> None:
        """Invalidate model-dependent views and append a replay snapshot."""
        self._refresh_datum_attachments(
            previous_sketches=previous_sketches,
            exact_reorder_annotations=exact_reorder_annotations,
        )
        self._identity_scope.invalidate_topology()
        self._boundary_topology_ids.clear()
        self._face_topology_ids.clear()
        self._vertex_topology_ids.clear()
        self._history_body_ids.clear()
        self._history_boundary_cache.clear()
        self._history_topology_cache.clear()
        self._feature_ids.append(self._identity_scope.new_feature_id())
        self._geometry_revision += 1
        self._current_mesh_cache.clear()
        self._current_boundary_cache.clear()
        self._current_topology_cache.clear()
        self._snapshots.append(
            (
                f"{command_id}:{len(self._snapshots)}",
                self._geometry_revision,
                deepcopy(self._part),
            )
        )

    @staticmethod
    def measure_planar_region(
        entities: tuple[SketchEntity, ...], point: Point2D
    ) -> SampledMeasuredRegion | None:
        """Measure an exact planar face and return only neutral display data."""
        from mycad.geom.drawing_spline_regions import measure_planar_region_at

        return measure_planar_region_at(entities, point)

    def offset_closed_path(
        self, source: PolylineEntity, distance: float, gap_type: int = 0
    ) -> tuple[PolylineEntity, ...]:
        """Compute closed straight-path offsets, including split components."""
        from mycad.geom.drawing_offset import offset_closed_path

        return offset_closed_path(source, distance, gap_type)

    def offset_spline(self, source: SplineEntity, distance: float) -> tuple[SplineEntity, ...]:
        """Compute a tolerance-controlled offset of an open drawing spline."""
        from mycad.geom.offset_spline import offset_spline

        return offset_spline(source, distance)

    def offset_ellipse(self, source: EllipseEntity, distance: float) -> tuple[SplineEntity, ...]:
        """Compute a tolerance-controlled offset of an ellipse or elliptic arc."""
        from mycad.geom.offset_ellipse import offset_ellipse

        return offset_ellipse(source, distance)

    def offset_spline_path(
        self, sources: tuple[SplineEntity, ...], distance: float
    ) -> tuple[SplineEntity, ...]:
        """Offset a connected path of spline pieces as a single curve."""
        from mycad.geom.offset_spline import offset_spline_path

        return offset_spline_path(sources, distance)

    @property
    def drawing_source_fingerprint(self) -> str:
        operations = [
            (operation.context.command_id, operation.params)
            for operation in self._operations
            if not operation.context.command_id.startswith(
                ("drawing.sheet.", "drawing.view.", "drawing.annotation.", "drawing.note.")
            )
        ]
        return hashlib.sha256(
            json.dumps(operations, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def drawing_snapshot(self) -> DrawingSourceSnapshot:
        if self._part is None or not self._part.solids():
            raise ValueError("Cannot create a view from an empty source model")
        stream = BytesIO()
        write_brep = cast("Callable[[Part, BytesIO], bool]", build123d.export_brep)
        if not write_brep(self._part, stream):
            raise ValueError("Could not serialize drawing source")
        return DrawingSourceSnapshot(self.drawing_source_fingerprint, stream.getvalue())

    def project_drawing(self, request: DrawingProjectionRequest) -> ProjectionResult:
        if request.source_fingerprint != self.drawing_source_fingerprint:
            raise ValueError("Drawing source has changed")
        if request.source == "sketch":
            from mycad.core.drawing_sketch import project_sketch

            sketch = self._sketches.get(request.sketch_id or "")
            if sketch is None:
                raise ValueError("草图来源不存在，请重新选择来源")
            return project_sketch(sketch, request)
        if self._part is None or not self._part.solids():
            raise ValueError("Cannot create a view from an empty source model")
        if request.section is not None:
            return project_section(
                self._part, request.section, request, request.hatch_spacing_mm
            ).projection
        if request.detail is not None:
            parent = project_shape(self._part, request)
            return clip_detail_projection(
                parent,
                request.detail,
                request.view_id,
                request.generation,
                clipper=clip_detail_exact,
            )
        key = (request.source_fingerprint, request.basis)
        if key not in self._drawing_projection_cache:
            if len(self._drawing_projection_cache) >= 24:
                self._drawing_projection_cache.clear()
            self._drawing_projection_cache[key] = project_shape(self._part, request)
        return replace(
            self._drawing_projection_cache[key],
            view_id=request.view_id,
            generation=request.generation,
        )

    @property
    def drawing_state(self) -> DrawingState:
        """Immutable engineering drawing objects reconstructed by command replay."""
        return self._drawing_state

    @property
    def drawing_revision(self) -> int:
        return self._drawing_revision

    def _apply_drawing_block(self, command_id: str, params: Mapping[str, object]) -> None:
        """Validate block collections completely before publishing a command result."""
        definitions = self._drawing_block_definitions
        instances = self._drawing_block_instances
        groups = self._drawing_groups
        origins = self._drawing_block_library_origins

        def definition_for(identity: str) -> BlockDefinition:
            for item in definitions:
                if item.definition_id == identity:
                    return item
            raise ValueError("块定义不存在。")

        def check_layer(name: str) -> None:
            layer = self.drawing_layers.get(name)
            if layer.locked or not layer.displayed:
                raise ValueError(f"块使用的图层 {name} 隐藏、冻结或已锁定。")

        def check_definition(
            definition: BlockDefinition, *, check_locks: bool = True, check_zero: bool = True
        ) -> None:
            for item in (*definition.entities, *definition.texts):
                if check_locks and (check_zero or item.layer_name.casefold() != "0"):
                    check_layer(item.layer_name)
                else:
                    self.drawing_layers.get(item.layer_name)
            for item in definition.texts:
                self._drawing_text_styles.get(item.style_id)

        def check_instance(instance: BlockInstance, definition: BlockDefinition) -> None:
            validate_block_instance(
                definition, instance, self.drawing_layers, self._drawing_text_styles
            )

        try:
            if command_id == "drawing.block_library.bind":
                origin = BlockLibraryOrigin(
                    cast("str", params["definition_id"]),
                    cast("str", params["asset_id"]),
                    cast("str", params["content_sha256"]),
                )
                definition_for(origin.definition_id)
                previous = next(
                    (item for item in origins if item.definition_id == origin.definition_id), None
                )
                if previous is not None and previous != origin:
                    raise ValueError("块定义已有不同的库来源。")
                if previous is None:
                    origins = (*origins, origin)
            elif command_id == "drawing.block.create":
                definition = BlockDefinition.from_mapping(params)
                # A definition has no effective layer until an instance is inserted.
                # Insertion validates layer 0 members against that instance's layer.
                check_definition(definition, check_zero=False)
                definitions = (*definitions, definition)
            elif command_id == "drawing.block.update":
                definition = BlockDefinition.from_mapping(params)
                previous = definition_for(definition.definition_id)
                affected = tuple(
                    item for item in instances if item.definition_id == definition.definition_id
                )
                validate_block_definition_edit(
                    previous, affected, self.drawing_layers, self._drawing_text_styles
                )
                validate_block_definition_edit(
                    definition, affected, self.drawing_layers, self._drawing_text_styles
                )
                definitions = tuple(
                    definition if item.definition_id == definition.definition_id else item
                    for item in definitions
                )
            elif command_id == "drawing.block.remove":
                identity = cast("str", params["definition_id"])
                definition = definition_for(identity)
                if any(item.definition_id == identity for item in instances):
                    raise ValueError("块定义仍被实例引用，不能删除。")
                validate_block_definition_edit(
                    definition, (), self.drawing_layers, self._drawing_text_styles
                )
                definitions = tuple(item for item in definitions if item.definition_id != identity)
                origins = tuple(item for item in origins if item.definition_id != identity)
            elif command_id in {"drawing.block_instance.insert", "drawing.block_instance.update"}:
                instance = BlockInstance.from_mapping(params)
                definition = definition_for(instance.definition_id)
                check_instance(instance, definition)
                if command_id == "drawing.block_instance.insert":
                    instances = (*instances, instance)
                else:
                    previous = next(
                        (item for item in instances if item.instance_id == instance.instance_id),
                        None,
                    )
                    if previous is None or previous.definition_id != instance.definition_id:
                        raise ValueError("块实例不存在或定义身份已变化。")
                    check_instance(previous, definition)
                    instances = tuple(
                        instance if item.instance_id == instance.instance_id else item
                        for item in instances
                    )
            elif command_id == "drawing.block_instance.remove":
                identity = cast("str", params["instance_id"])
                previous = next((item for item in instances if item.instance_id == identity), None)
                if previous is None:
                    raise ValueError("块实例不存在。")
                check_instance(previous, definition_for(previous.definition_id))
                instances = tuple(item for item in instances if item.instance_id != identity)
                groups = groups.without_members((DrawingObjectRef("block_instance", identity),))
            else:
                raise ValueError("不支持的块命令。")
            state = DrawingCollectionState(groups, definitions, instances, origins)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._drawing_groups = state.groups
        self._drawing_block_definitions = state.block_definitions
        self._drawing_block_instances = state.block_instances
        self._drawing_block_library_origins = state.block_library_origins
        self._drawing_revision += 1
        self._record_sketch_change(command_id)

    def _drawing_object_catalog(self) -> DrawingObjectCatalog:
        refs = [
            DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
            for sketch in self._sketches.values()
            for entity in sketch.entities
        ]
        refs.extend(
            DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
            for sketch in self._sketches.values()
            for constraint in sketch.constraints
            if constraint.kind in DIMENSION_KINDS
        )
        refs.extend(DrawingObjectRef("text", identity) for identity in self._drawing_texts)
        refs.extend(DrawingObjectRef("raster", identity) for identity in self._drawing_rasters)
        refs.extend(
            DrawingObjectRef("block_instance", item.instance_id)
            for item in self._drawing_block_instances
        )
        refs.extend(DrawingObjectRef("tolerance", identity) for identity in self._tolerance_frames)
        refs.extend(DrawingObjectRef("datum", identity) for identity in self._datum_identifiers)
        refs.extend(
            DrawingObjectRef("reference_dimension", identity)
            for identity in self._reference_dimensions
        )
        return DrawingObjectCatalog(tuple(refs))

    def _validate_drawing_group_arrays(self, groups: tuple[DrawingGroup, ...]) -> None:
        array_refs = {
            (ref.sketch_id, ref.entity_id)
            for array in self._associative_arrays.values()
            for ref in (
                *array.sources,
                *(member.target for member in array.members),
                *(output.target for output in array.extra_outputs),
            )
        }
        if any(
            member.kind == "geometry" and (member.sketch_id, member.object_id) in array_refs
            for group in groups
            for member in group.members
        ):
            raise ValidationError("关联阵列来源或成员暂不支持编组。")

    @property
    def drawing_group_array_conflicts(self) -> frozenset[tuple[str, str, str, str]]:
        """Return replacement-source conflicts without invalidating older histories."""
        if not self._drawing_groups.groups or not self._associative_arrays:
            return frozenset()
        refs: dict[tuple[str, str], set[str]] = {}
        for array in self._associative_arrays.values():
            for ref in (
                *(
                    member.replacement.source
                    for member in array.members
                    if member.replacement is not None
                ),
                *(output.source for output in array.extra_outputs),
            ):
                refs.setdefault((ref.sketch_id, ref.entity_id), set()).add(array.array_id)
        return frozenset(
            (group.group_id, array_id, member.sketch_id or "", member.object_id)
            for group in self._drawing_groups.groups
            for member in group.members
            if member.kind == "geometry"
            for array_id in refs.get((member.sketch_id or "", member.object_id), ())
        )

    @property
    def drawing_identity_reservations(self) -> tuple[str, ...]:
        """Live drawing identities used to guard generated object identities."""
        return tuple(
            dict.fromkeys(
                (
                    *(ref.object_id for ref in self._drawing_object_catalog().objects),
                    *(sketch.sketch_id for sketch in self._sketches.values()),
                    *self._cross_tangencies,
                    *self._associative_arrays,
                    *(
                        constraint.constraint_id
                        for sketch in self._sketches.values()
                        for constraint in sketch.constraints
                    ),
                    *(
                        identity
                        for sketch in self._sketches.values()
                        for entity in sketch.entities
                        if isinstance(entity, PolylineEntity | SplineEntity)
                        for identity in entity.point_ids
                    ),
                )
            )
        )

    @property
    def drawing_groups(self) -> tuple[DrawingGroup, ...]:
        return self._drawing_groups.groups

    @property
    def drawing_block_definitions(self) -> tuple[BlockDefinition, ...]:
        return self._drawing_block_definitions

    @property
    def drawing_block_library_origins(self) -> tuple[BlockLibraryOrigin, ...]:
        return self._drawing_block_library_origins

    @property
    def drawing_block_instances(self) -> tuple[BlockInstance, ...]:
        return self._drawing_block_instances

    @property
    def drawing_rasters(self) -> tuple[DrawingRaster, ...]:
        """Embedded image references reconstructed by drawing history replay."""
        return tuple(self._drawing_rasters.values())

    @property
    def drawing_layers(self) -> SketchLayerTable:
        """Shared drawing properties, including the default annotation layer."""
        tables = tuple(sketch.layers for sketch in self._sketches.values())
        if self._drawing_layers_override is not None:
            tables = (*tables, self._drawing_layers_override)
        return merge_layer_tables(*tables, include_dim=self._drawing_layers_override is None)

    @property
    def dimension_layer(self) -> str:
        return self._dimension_layer

    @property
    def drawing_dimension_styles(self) -> DimensionStyleTable:
        """Drawing-local dimension styles reconstructed from command history."""
        return self._drawing_dimension_styles

    def _validate_dimension_style_references(
        self, constraints: Sequence[SketchConstraint], command_id: str
    ) -> None:
        for constraint in constraints:
            tolerance = constraint.tolerance
            if constraint.style_name is not None:
                try:
                    style = self._drawing_dimension_styles.get(constraint.style_name)
                except KeyError as exc:
                    raise ValidationError(
                        "尺寸引用的标注样式不存在。", command_id=command_id
                    ) from exc
                if constraint.precision != style.precision or constraint.scale != style.scale:
                    raise ValidationError("尺寸格式与关联标注样式不一致。", command_id=command_id)
                if tolerance is None:
                    tolerance = (
                        style.angular_tolerance
                        if constraint.kind == "angle"
                        else style.linear_tolerance
                    )
            if (
                tolerance is not None
                and tolerance.mode != "none"
                and constraint.text_override is not None
                and constraint.text_override.count("<>") != 1
            ):
                raise ValidationError(
                    "启用公差的尺寸文字必须包含且只包含一个 <> 占位符。", command_id=command_id
                )

    @property
    def drawing_texts(self) -> tuple[DrawingText, ...]:
        """Independent immutable model-space text in insertion order."""
        return tuple(self._drawing_texts.values())

    @property
    def drawing_tolerance_frames(self) -> tuple[FeatureControlFrame, ...]:
        return tuple(self._tolerance_frames.values())

    @property
    def drawing_datum_identifiers(self) -> tuple[DatumIdentifier, ...]:
        return tuple(self._datum_identifiers.values())

    def _resolve_datum_attachment(self, datum: DatumIdentifier) -> tuple[float, float] | None:
        if datum.annotation_attachment is not None:
            return self._resolve_annotation_target(
                datum.annotation_attachment, self._tolerance_frames
            )
        return self._resolve_annotation_attachment(datum.attachment)

    def _resolve_annotation_target(
        self, ref: AnnotationAttachment, frames: Mapping[str, FeatureControlFrame]
    ) -> tuple[float, float] | None:
        if ref.kind == "frame":
            frame = frames.get(ref.object_id)
            if frame is None:
                return None
            angle = math.radians(frame.rotation_deg)
            x, y = ref.offset_mm
            return (
                frame.position_mm[0] + x * math.cos(angle) - y * math.sin(angle),
                frame.position_mm[1] + x * math.sin(angle) + y * math.cos(angle),
            )
        if ref.kind == "reference_dimension":
            dimension = self._reference_dimensions.get(ref.object_id)
            if dimension is None:
                return None
            return (
                dimension.location_mm[0] + ref.offset_mm[0],
                dimension.location_mm[1] + ref.offset_mm[1],
            )
        sketch = self._sketches.get(ref.sketch_id or "")
        if (
            sketch is None
            or abs(abs(sketch.frame.normal[2]) - 1.0) > 1e-9
            or abs(sketch.frame.origin_mm[2]) > 1e-7
        ):
            return None
        dimension = next(
            (
                item
                for item in sketch.constraints
                if item.constraint_id == ref.object_id and item.kind in DIMENSION_KINDS
            ),
            None,
        )
        if dimension is None:
            return None
        anchor = (
            dimension.text_position_mm
            if ref.anchor == "text" and dimension.text_position_mm is not None
            else dimension.position_mm
        )
        if anchor is None:
            return None
        point = (anchor[0] + ref.offset_mm[0], anchor[1] + ref.offset_mm[1])
        world = sketch.frame.local_to_world(point)
        return (world[0], world[1])

    def _resolve_annotation_attachment(
        self, attachment: DatumAttachment | None
    ) -> tuple[float, float] | None:
        from mycad.core.geometric_tolerance_attachment import resolve_attachment_local

        if attachment is None:
            return None
        sketch = self._sketches.get(attachment.sketch_id)
        if sketch is None:
            return None
        point = resolve_attachment_local(
            attachment, {entity.entity_id: entity for entity in sketch.entities}
        )
        if point is None:
            return None
        frame = sketch.frame
        if abs(abs(frame.normal[2]) - 1.0) > 1e-9 or abs(frame.origin_mm[2]) > 1e-7:
            return None
        world = tuple(
            frame.origin_mm[i] + point[0] * frame.u_axis[i] + point[1] * frame.v_axis[i]
            for i in range(3)
        )
        if not math.isclose(world[2], 0.0, abs_tol=1e-7):
            return None
        return (world[0], world[1])

    def datum_attachment_resolved(self, datum_id: str) -> bool:
        datum = self._datum_identifiers.get(datum_id)
        return (
            datum is not None
            and (datum.attachment is not None or datum.annotation_attachment is not None)
            and self._resolve_datum_attachment(datum) is not None
        )

    def _refresh_datum_attachments(
        self,
        *,
        previous_sketches: Mapping[str, Sketch] | None = None,
        exact_reorder_annotations: set[tuple[str, str]] | None = None,
    ) -> None:
        from mycad.core.geometric_tolerance_attachment import (
            resolve_attachment_normal,
            resolve_datum_bar_direction,
        )

        def side(
            vector: tuple[float, float],
            normal: tuple[float, float],
            attachment: DatumAttachment,
            old_target: tuple[float, float],
            *,
            enable_spline: bool,
        ) -> int:
            old_sketch = previous_sketches.get(attachment.sketch_id) if previous_sketches else None
            old_normal = (
                resolve_attachment_normal(
                    attachment, old_sketch, old_target, enable_spline=enable_spline
                )
                if old_sketch is not None
                else None
            )
            reference = old_normal if old_normal is not None else normal
            return -1 if vector[0] * reference[0] + vector[1] * reference[1] < -1e-12 else 1

        def follow_surface(
            surface: SurfaceIndication | None,
            attachment: DatumAttachment | None,
            target: tuple[float, float],
            old_target: tuple[float, float],
        ) -> SurfaceIndication | None:
            if surface is None or not surface.auto_normal or attachment is None:
                return surface
            sketch = self._sketches.get(attachment.sketch_id)
            normal = (
                resolve_attachment_normal(attachment, sketch, target, enable_spline=True)
                if sketch is not None
                else None
            )
            if normal is None:
                raise ValidationError("表面引线无法确定附着法向，请先解除法向约束。")
            previous = surface.leader_offsets_mm[0]
            length = math.hypot(*previous)
            sign = side(previous, normal, attachment, old_target, enable_spline=True)
            offset = (normal[0] * length * sign, normal[1] * length * sign)
            if math.dist(offset, previous) <= 1e-9:
                return surface
            try:
                if surface.auto_route:
                    route = _safe_orthogonal_leader_route(
                        (0.0, 0.0),
                        (surface.reference_start_offset_mm,),
                        offset,
                        (0.0, 0.0),
                        avoid_crossing=surface.route_avoid_crossing,
                    )
                    if len(route) < 2:
                        raise ValueError("表面引线法向顶点与参考线重合")
                    return replace(surface, leader_offsets_mm=tuple(reversed(route[1:])))
                return replace(surface, leader_offsets_mm=(offset, *surface.leader_offsets_mm[1:]))
            except ValueError as exc:
                raise ValidationError("表面引线法向更新失败，请先调整引线。") from exc

        for identity, frame in self._tolerance_frames.items():
            target = (
                self._resolve_annotation_target(
                    frame.leader_annotation_attachment, self._tolerance_frames
                )
                if frame.leader_annotation_attachment is not None
                else self._resolve_annotation_attachment(frame.leader_attachment)
            )
            if target is not None:
                preserve_geometry = ("frame", identity) in (exact_reorder_annotations or ())
                surface = (
                    frame.surface_indication
                    if preserve_geometry
                    else follow_surface(
                        frame.surface_indication,
                        frame.leader_attachment,
                        target,
                        frame.leader_target_mm if frame.leader_target_mm is not None else target,
                    )
                )
                offsets = frame.leader_offsets
                if (
                    not preserve_geometry
                    and frame.leader_auto_normal
                    and frame.leader_attachment is not None
                ):
                    sketch = self._sketches.get(frame.leader_attachment.sketch_id)
                    normal = (
                        resolve_attachment_normal(
                            frame.leader_attachment, sketch, target, enable_spline=True
                        )
                        if sketch is not None
                        else None
                    )
                    if normal is None or frame.leader_target_mm is None:
                        raise ValidationError("公差框主引线无法确定附着法向，请先解除约束。")
                    last = offsets[-1]
                    vertex = (frame.position_mm[0] + last[0], frame.position_mm[1] + last[1])
                    vector = (
                        vertex[0] - frame.leader_target_mm[0],
                        vertex[1] - frame.leader_target_mm[1],
                    )
                    length = math.hypot(*vector)
                    sign = side(
                        vector,
                        normal,
                        frame.leader_attachment,
                        frame.leader_target_mm,
                        enable_spline=True,
                    )
                    point = (
                        target[0] + normal[0] * length * sign,
                        target[1] + normal[1] * length * sign,
                    )
                    if (
                        len(offsets) > 1
                        and not frame.leader_auto_route
                        and math.dist(
                            point,
                            (
                                frame.position_mm[0] + offsets[-2][0],
                                frame.position_mm[1] + offsets[-2][1],
                            ),
                        )
                        <= 1e-9
                    ):
                        raise ValidationError(
                            "公差框主引线法向更新导致相邻顶点重合，请先调整引线。"
                        )
                    if math.dist(point, vertex) > 1e-9 or (
                        frame.route_track_target
                        and math.dist(target, frame.leader_target_mm) > 1e-9
                    ):
                        if (
                            frame.leader_auto_route
                            and frame.route_algorithm_version < 2
                            and offsets
                            and math.dist(
                                target,
                                (
                                    frame.position_mm[0] + offsets[0][0],
                                    frame.position_mm[1] + offsets[0][1],
                                ),
                            )
                            <= 1e-9
                        ):
                            raise ValidationError("自动引线与附着点重合，请先调整引线。")
                        offsets = (
                            _safe_orthogonal_leader_route(
                                frame.position_mm,
                                offsets,
                                point,
                                target,
                                avoid_crossing=frame.route_avoid_crossing,
                                guard_box=frame.route_algorithm_version >= 2,
                                anchor=(
                                    (
                                        frame.position_mm[0] + frame.leader_anchor_offset[0],
                                        frame.position_mm[1] + frame.leader_anchor_offset[1],
                                    )
                                    if frame.leader_anchor_offset is not None
                                    else None
                                ),
                            )
                            if frame.leader_auto_route
                            else (
                                *offsets[:-1],
                                (point[0] - frame.position_mm[0], point[1] - frame.position_mm[1]),
                            )
                        )
                if (
                    target != frame.leader_target_mm
                    or surface != frame.surface_indication
                    or offsets != frame.leader_offsets
                ):
                    self._tolerance_frames[identity] = replace(
                        frame,
                        leader_target_mm=target,
                        surface_indication=surface,
                        leader_offsets=offsets,
                    )
        for identity, datum in self._datum_identifiers.items():
            target = self._resolve_datum_attachment(datum)
            if datum.symbol_style == "circle":
                direction = resolve_datum_bar_direction(
                    replace(datum, target_mm=target) if target is not None else datum,
                    self._sketches,
                    self._tolerance_frames,
                )
                if direction != datum.bar_direction:
                    datum = replace(datum, bar_direction=direction)
                    self._datum_identifiers[identity] = datum
            if target is None:
                continue
            offsets = datum.leader_offsets
            preserve_geometry = ("datum", identity) in (exact_reorder_annotations or ())
            surface = (
                datum.surface_indication
                if preserve_geometry
                else follow_surface(
                    datum.surface_indication, datum.attachment, target, datum.target_mm
                )
            )
            if not preserve_geometry and datum.leader_auto_normal and datum.attachment is not None:
                sketch = self._sketches.get(datum.attachment.sketch_id)
                normal = (
                    resolve_attachment_normal(
                        datum.attachment,
                        sketch,
                        target,
                        enable_spline=datum.spline_normal_enabled,
                    )
                    if sketch is not None
                    else None
                )
                if normal is None and previous_sketches is not None and datum.spline_normal_enabled:
                    raise ValidationError("基准引线无法确定附着法向，请先解除法向约束。")
                if normal is not None:
                    last = offsets[-1]
                    vertex = (datum.position_mm[0] + last[0], datum.position_mm[1] + last[1])
                    vector = (vertex[0] - datum.target_mm[0], vertex[1] - datum.target_mm[1])
                    length = math.hypot(*vector)
                    sign = side(
                        vector,
                        normal,
                        datum.attachment,
                        datum.target_mm,
                        enable_spline=datum.spline_normal_enabled,
                    )
                    distance = length * sign
                    point = (target[0] + normal[0] * distance, target[1] + normal[1] * distance)
                    if (
                        previous_sketches is not None
                        and len(offsets) > 1
                        and not datum.leader_auto_route
                        and math.dist(point, vertex) > 1e-9
                        and math.dist(
                            point,
                            (
                                datum.position_mm[0] + offsets[-2][0],
                                datum.position_mm[1] + offsets[-2][1],
                            ),
                        )
                        <= 1e-9
                    ):
                        raise ValidationError("基准引线法向更新导致相邻顶点重合，请先调整引线。")
                    if math.dist(point, vertex) > 1e-9 or (
                        datum.route_track_target and math.dist(target, datum.target_mm) > 1e-9
                    ):
                        if (
                            datum.leader_auto_route
                            and datum.route_algorithm_version < 2
                            and offsets
                            and math.dist(
                                target,
                                (
                                    datum.position_mm[0] + offsets[0][0],
                                    datum.position_mm[1] + offsets[0][1],
                                ),
                            )
                            <= 1e-9
                        ):
                            raise ValidationError("自动引线与附着点重合，请先调整引线。")
                        if datum.leader_auto_route and datum.route_algorithm_version >= 3:
                            assert datum.box_size_mm is not None
                            x, y = datum.position_mm
                            width, height = datum.box_size_mm
                            try:
                                offsets = reroute_leader_around_box(
                                    datum.position_mm,
                                    offsets,
                                    point,
                                    target,
                                    (x, y, x + width, y - height),
                                    orthogonal_box_side=datum.route_algorithm_version >= 4,
                                )
                            except ValueError as exc:
                                raise ValidationError(str(exc)) from exc
                        elif datum.leader_auto_route:
                            offsets = _safe_orthogonal_leader_route(
                                datum.position_mm,
                                offsets,
                                point,
                                target,
                                avoid_crossing=datum.route_avoid_crossing,
                                guard_box=datum.route_algorithm_version >= 2,
                            )
                        else:
                            offsets = (
                                *offsets[:-1],
                                (point[0] - datum.position_mm[0], point[1] - datum.position_mm[1]),
                            )
            if (
                target != datum.target_mm
                or offsets != datum.leader_offsets
                or surface != datum.surface_indication
            ):
                self._datum_identifiers[identity] = replace(
                    datum, target_mm=target, leader_offsets=offsets, surface_indication=surface
                )

    @property
    def drawing_reference_dimensions(self) -> tuple[DetachedDimension, ...]:
        return tuple(self._reference_dimensions.values())

    def _apply_reference_dimensions(self, params: Mapping[str, object]) -> None:
        candidate = dict(self._reference_dimensions)
        seen: set[str] = set()
        try:
            for action in ("remove", "update", "add"):
                values = params.get(action, [])
                if not isinstance(values, list):
                    raise ValueError("参考尺寸批操作必须是数组。")
                for raw in cast("list[object]", values):
                    dimension = None if action == "remove" else DetachedDimension.from_mapping(raw)
                    if (
                        dimension is not None
                        and dimension.kind in ("radius", "diameter")
                        and self._active_execution_context is not None
                        and self._active_execution_context.command_version < 2
                    ):
                        raise ValueError("半径或直径参考尺寸需要命令版本 2。")
                    if (
                        dimension is not None
                        and dimension.kind == "angular_3p"
                        and self._active_execution_context is not None
                        and self._active_execution_context.command_version < 3
                    ):
                        raise ValueError("角度参考尺寸需要命令版本 3。")
                    if (
                        dimension is not None
                        and dimension.kind == "angular_3p"
                        and dimension.nominal > 180
                        and self._active_execution_context is not None
                        and self._active_execution_context.command_version < 7
                    ):
                        raise ValueError("反角参考尺寸需要命令版本 7。")
                    if (
                        dimension is not None
                        and dimension.kind == "angular_3p"
                        and abs(dimension.nominal - 180) <= 1e-9
                        and self._active_execution_context is not None
                        and self._active_execution_context.command_version < 9
                    ):
                        raise ValueError("180° 三点参考角需要命令版本 9。")
                    if (
                        dimension is not None
                        and dimension.kind == "angular_2l"
                        and self._active_execution_context is not None
                        and self._active_execution_context.command_version < 4
                    ):
                        raise ValueError("两线角度参考尺寸需要命令版本 4。")
                    if (
                        dimension is not None
                        and dimension.kind == "angular_2l"
                        and dimension.nominal > 180
                        and self._active_execution_context is not None
                        and self._active_execution_context.command_version < 8
                    ):
                        raise ValueError("两线反角参考尺寸需要命令版本 8。")
                    if (
                        dimension is not None
                        and dimension.kind in ("ordinate_x", "ordinate_y")
                        and self._active_execution_context is not None
                        and self._active_execution_context.command_version < 5
                    ):
                        raise ValueError("坐标参考尺寸需要命令版本 5。")
                    if (
                        dimension is not None
                        and dimension.kind in ("ordinate_x", "ordinate_y")
                        and dimension.angle_deg != 0
                        and self._active_execution_context is not None
                        and self._active_execution_context.command_version < 10
                    ):
                        raise ValueError("旋转坐标轴参考尺寸需要命令版本 10。")
                    identity = raw if dimension is None else dimension.dimension_id
                    if not isinstance(identity, str) or identity in seen:
                        raise ValueError("参考尺寸身份重复或无效。")
                    seen.add(identity)
                    previous = candidate.get(identity)
                    if (previous is None) != (action == "add"):
                        raise ValueError("参考尺寸不存在或身份已被使用。")
                    if previous is not None:
                        layer = self.drawing_layers.get(previous.layer_name)
                        if layer.locked or layer.frozen:
                            raise ValueError("锁定或冻结图层上的参考尺寸不能修改。")
                    if dimension is None:
                        del candidate[identity]
                    else:
                        layer = self.drawing_layers.get(dimension.layer_name)
                        if layer.locked or layer.frozen:
                            raise ValueError("不能在锁定或冻结图层上写入参考尺寸。")
                        candidate[identity] = dimension
            context = self._active_execution_context
            removed_ids = set(self._reference_dimensions) - set(candidate)
            for item in (*self._tolerance_frames.values(), *self._datum_identifiers.values()):
                ref = (
                    item.leader_annotation_attachment
                    if isinstance(item, FeatureControlFrame)
                    else item.annotation_attachment
                )
                if (
                    ref is not None
                    and ref.kind == "reference_dimension"
                    and ref.object_id in removed_ids
                ):
                    raise ValueError("参考尺寸仍被标注附着；请先解除附着。")
            if context is not None and context.command_version >= 6:
                new_ids = set(candidate) - set(self._reference_dimensions)
                if new_ids & (set(self._tolerance_frames) | set(self._datum_identifiers)):
                    raise ValueError("参考尺寸身份与形位公差或基准重复。")
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError(
                f"参考尺寸无效：{exc}", command_id="drawing.reference_dimensions.batch"
            ) from exc
        self._reference_dimensions = candidate
        self._refresh_datum_attachments()
        self._drawing_revision += 1
        self._snapshots.append(
            (
                f"drawing.reference_dimensions.batch:{len(self._snapshots)}",
                self._geometry_revision,
                self._part,
            )
        )

    def _apply_tolerance_batch(self, params: Mapping[str, object]) -> None:
        frames = dict(self._tolerance_frames)
        datums = dict(self._datum_identifiers)
        try:
            for suffix, collection, parse, identity_name in (
                (
                    "frames",
                    cast("dict[str, DatumIdentifier | FeatureControlFrame]", frames),
                    FeatureControlFrame.from_mapping,
                    "frame_id",
                ),
                (
                    "datums",
                    cast("dict[str, DatumIdentifier | FeatureControlFrame]", datums),
                    DatumIdentifier.from_mapping,
                    "datum_id",
                ),
            ):
                seen: set[str] = set()
                for action in ("remove", "update", "add"):
                    raw_items = params.get(f"{action}_{suffix}", [])
                    if not isinstance(raw_items, list):
                        raise ValueError("标注批操作必须是数组。")
                    for raw in cast("list[object]", raw_items):
                        item = None if action == "remove" else parse(raw)
                        identity = raw if item is None else getattr(item, identity_name)
                        if not isinstance(identity, str) or identity in seen:
                            raise ValueError("标注身份重复或无效。")
                        seen.add(identity)
                        previous = collection.get(identity)
                        if (previous is None) != (action == "add"):
                            raise ValueError("标注不存在或身份已被使用。")
                        if previous is not None:
                            layer = self.drawing_layers.get(previous.layer_name)
                            if layer.locked or layer.frozen:
                                raise ValueError("锁定或冻结图层上的标注不能修改。")
                        if item is None:
                            del collection[identity]
                        else:
                            layer = self.drawing_layers.get(item.layer_name)
                            if layer.locked or layer.frozen:
                                raise ValueError("不能在锁定或冻结图层上写入标注。")
                            if (
                                isinstance(item, FeatureControlFrame)
                                and isinstance(raw, Mapping)
                                and "leader_arrow_style" in raw
                                and self._active_execution_context is not None
                                and self._active_execution_context.command_version < 28
                            ):
                                raise ValueError("公差框引线箭头样式需要形位公差命令版本 28。")
                            if (
                                isinstance(item, DatumIdentifier)
                                and isinstance(raw, Mapping)
                                and "bar_direction" in raw
                                and self._active_execution_context is not None
                                and self._active_execution_context.command_version < 31
                            ):
                                raise ValueError("圆圈基准短线方向需要形位公差命令版本 31。")
                            if (
                                isinstance(item, DatumIdentifier)
                                and isinstance(raw, Mapping)
                                and "symbol_style" in raw
                                and self._active_execution_context is not None
                                and self._active_execution_context.command_version < 30
                            ):
                                raise ValueError("基准标识样式需要形位公差命令版本 30。")
                            if (
                                isinstance(item, DatumIdentifier)
                                and isinstance(raw, Mapping)
                                and "arrow_style" in raw
                                and self._active_execution_context is not None
                                and self._active_execution_context.command_version < 29
                            ):
                                raise ValueError("基准箭头样式需要形位公差命令版本 29。")
                            if isinstance(item, DatumIdentifier) and item.box_size_mm is not None:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 26:
                                    raise ValueError("基准框记录尺寸需要形位公差命令版本 26。")
                            if (
                                isinstance(item, DatumIdentifier)
                                and item.route_algorithm_version >= 3
                            ):
                                context = self._active_execution_context
                                if context is not None and context.command_version < 26:
                                    raise ValueError("基准框实际布线需要形位公差命令版本 26。")
                                if (
                                    item.route_algorithm_version >= 4
                                    and context is not None
                                    and context.command_version < 27
                                ):
                                    raise ValueError("基准框正交布线需要形位公差命令版本 27。")
                                assert item.box_size_mm is not None
                                x, y = item.position_mm
                                width, height = item.box_size_mm
                                if not box_aware_leader_is_safe(
                                    item.position_mm,
                                    item.leader_offsets,
                                    item.target_mm,
                                    (x, y, x + width, y - height),
                                ):
                                    raise ValueError("基准引线穿越标注框或附着首段。")
                                if (
                                    item.route_algorithm_version >= 4
                                    and not box_aware_leader_is_safe(
                                        item.position_mm,
                                        item.leader_offsets,
                                        item.target_mm,
                                        (x, y, x + width, y - height),
                                        orthogonal_box_side=True,
                                    )
                                ):
                                    raise ValueError("基准框侧引线必须正交，且目标不能位于框上。")
                            if item.route_algorithm_version >= 2:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 25:
                                    raise ValueError("引线框侧保护需要形位公差命令版本 25。")
                            if item.route_track_target:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 24:
                                    raise ValueError("引线目标跟踪需要形位公差命令版本 24。")
                            if item.route_avoid_crossing or (
                                item.surface_indication is not None
                                and item.surface_indication.route_avoid_crossing
                            ):
                                context = self._active_execution_context
                                if context is not None and context.command_version < 23:
                                    raise ValueError("引线防穿越策略需要形位公差命令版本 23。")
                            if item.leader_auto_route or (
                                item.surface_indication is not None
                                and item.surface_indication.auto_route
                            ):
                                context = self._active_execution_context
                                if context is not None and context.command_version < 22:
                                    raise ValueError("自动引线布线需要形位公差命令版本 22。")
                            if isinstance(item, DatumIdentifier) and item.spline_normal_enabled:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 19:
                                    raise ValueError("样条法向约束需要形位公差命令版本 19。")
                            if isinstance(item, FeatureControlFrame) and item.leader_auto_normal:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 21:
                                    raise ValueError("公差框主引线法向约束需要命令版本 21。")
                            annotation_attachment = (
                                item.attachment
                                if isinstance(item, DatumIdentifier)
                                else item.leader_attachment
                            )
                            annotation_target = (
                                item.annotation_attachment
                                if isinstance(item, DatumIdentifier)
                                else item.leader_annotation_attachment
                            )
                            if item.surface_indication is not None:
                                context = self._active_execution_context
                                if (
                                    item.surface_indication.auto_normal
                                    and context is not None
                                    and context.command_version < 20
                                ):
                                    raise ValueError("表面引线法向约束需要形位公差命令版本 20。")
                                if context is not None and context.command_version < 17:
                                    raise ValueError("表面指示线需要形位公差命令版本 17。")
                                if (
                                    item.surface_indication.arrow_size_mm is not None
                                    and context is not None
                                    and context.command_version < 18
                                ):
                                    raise ValueError("表面指示箭头尺寸需要形位公差命令版本 18。")
                            if (
                                annotation_attachment is not None
                                and annotation_attachment.surface_extension is not None
                            ):
                                context = self._active_execution_context
                                if context is not None and context.command_version < 16:
                                    raise ValueError("表面延伸线需要形位公差命令版本 16。")
                            if annotation_target is not None:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 14:
                                    raise ValueError("标注对象附着需要形位公差命令版本 14。")
                                if (
                                    annotation_target.anchor == "text"
                                    and context is not None
                                    and context.command_version < 15
                                ):
                                    raise ValueError("尺寸文字附着需要形位公差命令版本 15。")
                            if (
                                annotation_attachment is not None
                                and annotation_attachment.curve_kind == "ellipse"
                            ):
                                context = self._active_execution_context
                                if context is not None and context.command_version < 13:
                                    raise ValueError("椭圆附着需要形位公差命令版本 13。")
                            if isinstance(item, DatumIdentifier) and item.leader_offsets:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 8:
                                    raise ValueError("基准折线引线需要形位公差命令版本 8。")
                            if isinstance(item, DatumIdentifier) and not item.leader_visible:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 11:
                                    raise ValueError("无引线基准需要形位公差命令版本 11。")
                            if isinstance(item, DatumIdentifier) and item.layout_mode != "legacy":
                                context = self._active_execution_context
                                if context is not None and context.command_version < 12:
                                    raise ValueError("统一基准布局需要形位公差命令版本 12。")
                            if (
                                isinstance(item, FeatureControlFrame)
                                and item.leader_target_mm is not None
                            ):
                                context = self._active_execution_context
                                if context is not None and context.command_version < 9:
                                    raise ValueError("形位公差框引线需要形位公差命令版本 9。")
                                if (
                                    item.leader_attachment is not None
                                    and context is not None
                                    and context.command_version < 10
                                ):
                                    raise ValueError("形位公差框附着需要形位公差命令版本 10。")
                                if item.leader_attachment is not None:
                                    target = self._resolve_annotation_attachment(
                                        item.leader_attachment
                                    )
                                    changed = (
                                        not isinstance(previous, FeatureControlFrame)
                                        or previous.leader_attachment != item.leader_attachment
                                    )
                                    if (
                                        target is not None
                                        and math.dist(target, item.leader_target_mm) > 1e-7
                                    ):
                                        raise ValueError("公差框引线附着点与指定位置不一致。")
                                    if target is None and (
                                        changed
                                        or not isinstance(previous, FeatureControlFrame)
                                        or previous.leader_target_mm != item.leader_target_mm
                                    ):
                                        raise ValueError("公差框引线附着目标无法解析。")
                            if item.text_style_id is not None:
                                context = self._active_execution_context
                                required_version = 5 if isinstance(item, FeatureControlFrame) else 6
                                if (
                                    context is not None
                                    and context.command_version < required_version
                                ):
                                    raise ValueError(
                                        f"标注文字样式需要形位公差命令版本 {required_version}。"
                                    )
                                self._drawing_text_styles.get(item.text_style_id)
                            if isinstance(item, DatumIdentifier) and item.attachment is not None:
                                context = self._active_execution_context
                                if context is not None and context.command_version < 2:
                                    raise ValueError("基准附着需要形位公差命令版本 2。")
                                if (
                                    item.attachment.segment_kind == "rectangle"
                                    and context is not None
                                    and context.command_version < 3
                                ):
                                    raise ValueError("矩形边基准附着需要形位公差命令版本 3。")
                                if (
                                    item.attachment.curve_kind == "spline"
                                    and context is not None
                                    and context.command_version < 4
                                ):
                                    raise ValueError("样条基准附着需要形位公差命令版本 4。")
                                target = self._resolve_datum_attachment(item)
                                changed = (
                                    not isinstance(previous, DatumIdentifier)
                                    or previous.attachment != item.attachment
                                )
                                if target is not None and math.dist(target, item.target_mm) > 1e-7:
                                    raise ValueError("基准附着点与指定位置不一致。")
                                if target is None and (
                                    changed
                                    or not isinstance(previous, DatumIdentifier)
                                    or previous.target_mm != item.target_mm
                                ):
                                    raise ValueError("基准附着点不存在或最后位置被修改。")
                            collection[identity] = item
            context = self._active_execution_context
            if context is not None and context.command_version >= 7:
                new_frames = set(frames) - set(self._tolerance_frames)
                new_datums = set(datums) - set(self._datum_identifiers)
                if new_frames & (set(datums) | set(self._reference_dimensions)) or new_datums & (
                    set(frames) | set(self._reference_dimensions)
                ):
                    raise ValueError("形位公差、基准或参考尺寸的身份重复。")
            datum_names = [datum.label.casefold() for datum in datums.values()]
            if len(datum_names) != len(set(datum_names)):
                raise ValueError("基准名称不能重复。")
            for identity in frames:
                seen_frames: set[str] = set()
                current = identity
                while current in frames:
                    if current in seen_frames:
                        raise ValueError("公差框附着不能形成循环。")
                    seen_frames.add(current)
                    reference = frames[current].leader_annotation_attachment
                    if reference is None or reference.kind != "frame":
                        break
                    current = reference.object_id
            for item in (*frames.values(), *datums.values()):
                reference = (
                    item.leader_annotation_attachment
                    if isinstance(item, FeatureControlFrame)
                    else item.annotation_attachment
                )
                if reference is None:
                    continue
                target = self._resolve_annotation_target(reference, frames)
                if (
                    reference.kind == "frame"
                    and reference.object_id in self._tolerance_frames
                    and reference.object_id not in frames
                ):
                    raise ValueError("公差框仍被标注附着；请先解除附着或一并删除。")
                prior = (
                    self._tolerance_frames.get(item.frame_id)
                    if isinstance(item, FeatureControlFrame)
                    else self._datum_identifiers.get(item.datum_id)
                )
                old_ref = (
                    prior.leader_annotation_attachment
                    if isinstance(prior, FeatureControlFrame)
                    else prior.annotation_attachment
                    if isinstance(prior, DatumIdentifier)
                    else None
                )
                old_target = (
                    prior.leader_target_mm
                    if isinstance(prior, FeatureControlFrame)
                    else prior.target_mm
                    if isinstance(prior, DatumIdentifier)
                    else None
                )
                specified = (
                    item.leader_target_mm
                    if isinstance(item, FeatureControlFrame)
                    else item.target_mm
                )
                changed = old_ref != reference or old_target != specified
                if target is None and changed:
                    raise ValueError("标注附着目标无法解析。")
                if (
                    target is not None
                    and changed
                    and (specified is None or math.dist(target, specified) > 1e-7)
                ):
                    raise ValueError("标注附着点与指定位置不一致。")
            for identity, frame in frames.items():
                rows: list[ToleranceRow] = []
                for row in frame.rows:
                    refs: list[DatumReference] = []
                    for ref in row.datums:
                        if ref.datum_id is not None:
                            if ref.datum_id not in datums:
                                raise ValueError("被引用的基准不存在，不能删除。")
                            if ref.label != datums[ref.datum_id].label:
                                frame_layer = self.drawing_layers.get(frame.layer_name)
                                if frame_layer.locked or frame_layer.frozen:
                                    raise ValueError("锁定或冻结图层上的公差框不能修改。")
                            ref = replace(ref, label=datums[ref.datum_id].label)
                        refs.append(ref)
                    rows.append(replace(row, datums=tuple(refs)))
                frames[identity] = replace(frame, rows=tuple(rows))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError(
                f"形位公差或基准无效：{exc}", command_id="drawing.tolerance.batch"
            ) from exc
        self._tolerance_frames, self._datum_identifiers = frames, datums
        self._refresh_datum_attachments()
        self._drawing_revision += 1
        self._snapshots.append(
            (f"drawing.tolerance.batch:{len(self._snapshots)}", self._geometry_revision, self._part)
        )

    @property
    def drawing_text_styles(self) -> TextStyleTable:
        return self._drawing_text_styles

    def _apply_drawing_text(self, command_id: str, params: Mapping[str, object]) -> None:
        """Validate the entire candidate before publishing any text or style changes."""
        candidate = dict(self._drawing_texts)
        candidate_datums = dict(self._datum_identifiers)
        styles = self._drawing_text_styles
        try:
            if command_id == "drawing.text_styles.set":
                styles = TextStyleTable.from_mapping(
                    {"styles": params["styles"], "current_id": params["current_id"]}
                )
                batch: Mapping[str, object] = {}
            elif command_id == "drawing.text.batch":
                batch = params
                if "styles" in batch:
                    styles = TextStyleTable.from_mapping(batch["styles"])
            elif command_id == "drawing.text.remove":
                batch = {"remove": [params["text_id"]]}
            else:
                batch = {"add" if command_id == "drawing.text.add" else "update": [params]}
            seen: set[str] = set()
            for action in ("remove", "update", "add"):
                raw_items = batch.get(action, [])
                if not isinstance(raw_items, list):
                    raise ValueError("文字批操作必须是数组。")
                for raw in cast("list[object]", raw_items):
                    item = None if action == "remove" else DrawingText.from_mapping(raw)
                    identity = raw if item is None else item.text_id
                    if not isinstance(identity, str) or identity in seen:
                        raise ValueError("文字身份重复或无效。")
                    seen.add(identity)
                    existing = candidate.get(identity)
                    if (existing is None) != (action == "add"):
                        raise ValueError("文字不存在或身份已被使用。")
                    if existing is not None:
                        layer = self.drawing_layers.get(existing.layer_name)
                        if layer.locked or layer.frozen:
                            raise ValueError("锁定或冻结图层上的文字不能修改。")
                    if item is None:
                        del candidate[identity]
                    else:
                        layer = self.drawing_layers.get(item.layer_name)
                        if layer.locked or layer.frozen:
                            raise ValueError("不能在锁定或冻结图层上写入文字。")
                        candidate[identity] = item

            # A measured datum box must change atomically with its source style.
            # Width and height are supplied by the client and retained in history;
            # replay does not measure fonts on the current machine.
            required_updates: set[str] = set()
            for datum in self._datum_identifiers.values():
                if datum.box_size_mm is None or datum.text_style_id is None:
                    continue
                old_style = self._drawing_text_styles.get(datum.text_style_id)
                new_style = styles.get(datum.text_style_id)
                if text_style_geometry_signature(old_style) != text_style_geometry_signature(
                    new_style
                ):
                    required_updates.add(datum.datum_id)
            raw_updates: object = (
                params.get("datum_updates", []) if command_id == "drawing.text_styles.set" else []
            )
            if not isinstance(raw_updates, list):
                raise ValueError("基准框更新必须是数组。")
            updated_ids: set[str] = set()
            for raw in cast("list[object]", raw_updates):
                updated = DatumIdentifier.from_mapping(raw)
                previous = candidate_datums.get(updated.datum_id)
                if previous is None or updated.datum_id in updated_ids:
                    raise ValueError("基准框更新身份无效或重复。")
                if updated.datum_id not in required_updates or updated.box_size_mm is None:
                    raise ValueError("基准框更新与样式变更不匹配。")
                if (
                    replace(
                        updated,
                        box_size_mm=previous.box_size_mm,
                        leader_offsets=previous.leader_offsets,
                    )
                    != previous
                ):
                    raise ValueError("基准框更新包含无关修改。")
                layer = self.drawing_layers.get(previous.layer_name)
                if layer.locked or layer.frozen:
                    raise ValueError("锁定或冻结图层上的基准框不能修改。")
                if updated.route_algorithm_version >= 3:
                    assert updated.box_size_mm is not None
                    x, y = updated.position_mm
                    normal = (x + updated.leader_offsets[-1][0], y + updated.leader_offsets[-1][1])
                    expected = reroute_leader_around_box(
                        updated.position_mm,
                        updated.leader_offsets,
                        normal,
                        updated.target_mm,
                        (x, y, x + updated.box_size_mm[0], y - updated.box_size_mm[1]),
                        orthogonal_box_side=updated.route_algorithm_version >= 4,
                    )
                    if len(expected) != len(updated.leader_offsets) or any(
                        math.dist(a, b) > 1e-9
                        for a, b in zip(expected, updated.leader_offsets, strict=True)
                    ):
                        raise ValueError("基准框自动引线与更新尺寸不匹配。")
                candidate_datums[updated.datum_id] = updated
                updated_ids.add(updated.datum_id)
            if updated_ids != required_updates:
                raise ValueError("文字样式变化需要同步更新基准框尺寸。")

            for item in candidate.values():
                styles.get(item.style_id)
                self.drawing_layers.get(item.layer_name)
            for dimension_style in self._drawing_dimension_styles.styles:
                if dimension_style.text_style_id is not None:
                    try:
                        styles.get(dimension_style.text_style_id)
                    except KeyError as exc:
                        raise ValueError("文字样式仍被标注样式使用，不能删除。") from exc
            for annotation in (*self._tolerance_frames.values(), *self._datum_identifiers.values()):
                if annotation.text_style_id is not None:
                    try:
                        styles.get(annotation.text_style_id)
                    except KeyError as exc:
                        raise ValueError("文字样式仍被形位公差或基准标识使用，不能删除。") from exc
            for definition in self._drawing_block_definitions:
                for text in definition.texts:
                    try:
                        styles.get(text.style_id)
                    except KeyError as exc:
                        raise ValueError("文字样式仍被块定义使用，不能删除。") from exc
            if styles != self._drawing_text_styles:
                definitions = {
                    definition.definition_id: definition
                    for definition in self._drawing_block_definitions
                }
                for instance in self._drawing_block_instances:
                    try:
                        expand_block(definitions[instance.definition_id], instance, styles)
                    except (OverflowError, ValueError) as exc:
                        raise ValueError(f"文字样式导致块实例无法展开：{exc}") from exc
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError(f"文字或样式无效：{exc}", command_id=command_id) from exc
        self._drawing_texts = candidate
        self._datum_identifiers = candidate_datums
        self._drawing_text_styles = styles
        self._drawing_revision += 1
        self._snapshots.append(
            (f"{command_id}:{len(self._snapshots)}", self._geometry_revision, self._part)
        )

    def _set_drawing_layers(self, params: Mapping[str, object]) -> None:
        table = SketchLayerTable.from_mapping(params.get("layers"))
        target = params.get("dimension_layer", "DIM")
        if not isinstance(target, str):
            raise ValidationError("dimension layer must be a drawing layer name")
        if target != ".":
            table.get(target)
        assignments = params.get("assignments", [])
        if not isinstance(assignments, list):
            raise ValidationError("dimension assignments must be an array")
        sketches = {
            identity: replace(sketch, layers=table) for identity, sketch in self._sketches.items()
        }
        for raw in cast("list[object]", assignments):
            if not isinstance(raw, Mapping):
                raise ValidationError("invalid dimension layer assignment")
            record = cast("Mapping[str, object]", raw)
            identity, ids, name = (
                record.get("sketch_id"),
                record.get("constraint_ids"),
                record.get("layer_name"),
            )
            if (
                not isinstance(identity, str)
                or identity not in sketches
                or not isinstance(ids, list)
                or not isinstance(name, str)
            ):
                raise ValidationError("invalid dimension layer assignment")
            table.get(name)
            sketch = sketches[identity]
            selected = cast("list[object]", ids)
            known = {c.constraint_id for c in sketch.constraints if c.kind in DIMENSION_KINDS}
            if not selected or any(
                not isinstance(item, str) or item not in known for item in selected
            ):
                raise ValidationError("dimension assignment references a missing dimension")
            constraints = tuple(
                replace(c, layer_name=name) if c.constraint_id in selected else c
                for c in sketch.constraints
            )
            sketches[identity] = replace(sketch, constraints=constraints)
        # Validate the complete result before publishing any state.
        for sketch in sketches.values():
            for entity in sketch.entities:
                table.get(entity.layer_name)
            for constraint in sketch.constraints:
                if constraint.layer_name is not None:
                    table.get(constraint.layer_name)
        for text in self._drawing_texts.values():
            try:
                table.get(text.layer_name)
            except KeyError as exc:
                raise ValidationError("图层仍被文字使用，不能删除。") from exc
        for annotation in (*self._tolerance_frames.values(), *self._datum_identifiers.values()):
            try:
                table.get(annotation.layer_name)
            except KeyError as exc:
                raise ValidationError("图层仍被形位公差或基准使用，不能删除。") from exc
        for dimension in self._reference_dimensions.values():
            try:
                table.get(dimension.layer_name)
            except KeyError as exc:
                raise ValidationError("图层仍被独立参考尺寸使用，不能删除。") from exc
        for image in self._drawing_rasters.values():
            try:
                table.get(image.layer_name)
            except KeyError as exc:
                raise ValidationError("图层仍被图片使用，不能删除。") from exc
        for definition in self._drawing_block_definitions:
            for member in (*definition.entities, *definition.texts):
                try:
                    table.get(member.layer_name)
                except KeyError as exc:
                    raise ValidationError("图层仍被块定义使用，不能删除。") from exc
        for instance in self._drawing_block_instances:
            try:
                table.get(instance.layer_name)
            except KeyError as exc:
                raise ValidationError("图层仍被块实例使用，不能删除。") from exc
        self._sketches = sketches
        self._drawing_layers_override = table
        self._dimension_layer = target
        self._record_sketch_change("drawing.layers.set")

    @property
    def drawing_fillet_radius(self) -> float:
        """Current drawing fillet radius reconstructed from command history."""
        return self._drawing_fillet_radius

    @property
    def drawing_chamfer_values(self) -> tuple[float, float, float, float]:
        """Chamfer distances and angle reconstructed from drawing history."""
        return self._drawing_chamfer_values

    @property
    def sketches(self) -> tuple[Sketch, ...]:
        """Immutable sketch values reconstructed from replayed commands."""
        return tuple(self._sketches.values())

    @property
    def cross_sketch_tangencies(self) -> tuple[CrossSketchTangency, ...]:
        """Document-level tangent relations in deterministic identity order."""
        return tuple(self._cross_tangencies[key] for key in sorted(self._cross_tangencies))

    @property
    def associative_arrays(self) -> tuple[AssociativeRectArray, ...]:
        """Associative rectangular arrays reconstructed from command history."""
        return tuple(self._associative_arrays[key] for key in sorted(self._associative_arrays))

    def sketch_region_data(self, sketch: Sketch) -> tuple[ViewportSketchRegion, ...]:
        """Tessellate exact sketch regions without modifying the accepted model."""
        from mycad.geom.sketch_profiles import make_sketch_regions

        result: list[ViewportSketchRegion] = []
        for region in make_sketch_regions(sketch):
            vertices, triangles = region.face.tessellate(0.1, math.radians(10.0))
            mesh = Tessellation(
                vertices=tuple((float(v.X), float(v.Y), float(v.Z)) for v in vertices),
                triangle_indices=tuple((int(a), int(b), int(c)) for a, b, c in triangles),
            )
            result.append(
                ViewportSketchRegion(region.boundary_entity_ids, mesh, region.hole_entity_ids)
            )
        return tuple(result)

    def preview_sketch_constraint(
        self, sketch: Sketch, constraint: SketchConstraint
    ) -> SketchConstraintSolveResult:
        """Solve a disposable constraint preview through the optional geom adapter."""
        from mycad.geom.sketch_constraints import solve_sketch_constraint

        return solve_sketch_constraint(sketch, constraint)

    def preview_sketch_constraint_update(
        self, sketch: Sketch, constraint: SketchConstraint
    ) -> SketchConstraintSolveResult:
        """Preview an existing dimension revision without changing accepted state."""
        from mycad.geom.sketch_constraints import solve_sketch_constraint_update

        return solve_sketch_constraint_update(sketch, constraint)

    def preview_sketch_drag(
        self,
        sketch: Sketch,
        reference: SketchGeometryReference,
        target_mm: tuple[float, float],
    ) -> SketchConstraintSolveResult:
        """Solve a disposable point drag without mutating the active kernel."""
        from mycad.geom.sketch_constraints import solve_sketch_drag

        return solve_sketch_drag(sketch, reference, target_mm)

    def datum_display_data(self) -> tuple[ViewportDatum, ...]:
        """Expose spatial outputs without requiring a solid or mesh."""
        result: list[ViewportDatum] = []
        for identity, (kind, frame) in self._spatial_outputs.items():
            if kind == "coordinate_system" and isinstance(frame, RigidFrame):
                reference = SpatialReference("coordinate_system", identity, "coordinate_system")
            elif kind == "datum_plane" and isinstance(frame, WorkPlaneFrame):
                reference = SpatialReference("datum_plane", identity, "plane")
            else:
                raise ValueError("invalid evaluated spatial output")
            result.append(ViewportDatum(reference, self._spatial_names[identity], frame))
        return tuple(result)

    def snap_anchor_data(self) -> tuple[ViewportSnapAnchor, ...]:
        """Extract exact visible BREP vertices, curve midpoints and circle centers."""
        anchors: list[ViewportSnapAnchor] = []
        for sketch in self._sketches.values():
            for entity in sketch.entities:
                if not sketch.layers.get(entity.layer_name).displayed:
                    continue
                points: list[tuple[str, tuple[float, float]]] = []
                if isinstance(entity, PointEntity):
                    points.append(("vertex", entity.position_mm))
                elif isinstance(entity, LineEntity):
                    start, end = entity.start_mm, entity.end_mm
                    points.extend(("vertex", point) for point in (start, end))
                    points.append(("midpoint", ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)))
                elif isinstance(entity, CircleEntity):
                    points.append(("center", entity.center_mm))
                elif isinstance(entity, ArcEntity):
                    points.append(("center", entity.center_mm))
                    for kind, angle in (
                        ("vertex", entity.start_angle_deg),
                        ("midpoint", entity.start_angle_deg + entity.sweep_angle_deg / 2),
                        ("vertex", entity.start_angle_deg + entity.sweep_angle_deg),
                    ):
                        radians = math.radians(angle)
                        points.append(
                            (
                                kind,
                                (
                                    entity.center_mm[0] + entity.radius_mm * math.cos(radians),
                                    entity.center_mm[1] + entity.radius_mm * math.sin(radians),
                                ),
                            )
                        )
                elif isinstance(entity, PolylineEntity) and entity.bulges:
                    points.extend(("vertex", point) for point in entity.points_mm)
                    for segment in polyline_curve_segments(
                        entity.points_mm, entity.bulges, entity.closed, entity.entity_id
                    ):
                        if isinstance(segment, ArcEntity):
                            angle = math.radians(
                                segment.start_angle_deg + segment.sweep_angle_deg / 2
                            )
                            points.append(("center", segment.center_mm))
                            points.append(
                                (
                                    "midpoint",
                                    (
                                        segment.center_mm[0] + segment.radius_mm * math.cos(angle),
                                        segment.center_mm[1] + segment.radius_mm * math.sin(angle),
                                    ),
                                )
                            )
                        else:
                            points.append(
                                (
                                    "midpoint",
                                    (
                                        (segment.start_mm[0] + segment.end_mm[0]) / 2,
                                        (segment.start_mm[1] + segment.end_mm[1]) / 2,
                                    ),
                                )
                            )
                elif isinstance(entity, SplineEntity):
                    points.extend(
                        ("vertex", point) for point in (entity.point_at(0), entity.point_at(1))
                    )
                elif isinstance(entity, EllipseEntity):
                    points.append(("center", entity.center_mm))
                    if not entity.closed:
                        points.extend(
                            ("vertex", point) for point in (entity.point_at(0), entity.point_at(1))
                        )
                else:
                    if isinstance(entity, PolylineEntity):
                        anchors_vertices = entity.points_mm
                        vertices = entity.points_mm + (
                            (entity.points_mm[0],) if entity.closed else ()
                        )
                    else:
                        x1, y1 = entity.first_corner_mm
                        x2, y2 = entity.opposite_corner_mm
                        vertices = ((x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1))
                        anchors_vertices = vertices[:-1]
                    points.extend(("vertex", point) for point in anchors_vertices)
                    for start, end in zip(vertices, vertices[1:], strict=False):
                        points.append(
                            ("midpoint", ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2))
                        )
                for index, (kind, point) in enumerate(points):
                    anchors.append(
                        ViewportSnapAnchor(
                            cast("Literal['vertex', 'midpoint', 'center']", kind),
                            sketch.frame.local_to_world(point),
                            None,
                            None,
                            f"{sketch.sketch_id}:{entity.entity_id}:{index}",
                        )
                    )
        snapshots = self.viewport_data()
        if not snapshots or self._part is None:
            return tuple(anchors)
        snapshot = snapshots[-1]
        anchors.extend(
            ViewportSnapAnchor("vertex", vertex.point, vertex.body_id, vertex.topology_id)
            for vertex in snapshot.vertices
        )
        visible_edges = {edge.topology_id for edge in snapshot.boundary_edges}
        for body_index, (body_id, solid) in enumerate(
            zip(self._body_ids, self._part.solids(), strict=True)
        ):
            faces = solid.faces()
            if len(faces) == 1 and faces[0].geom_type == GeomType.SPHERE:
                surface = cast("_SphereFace", faces[0]).geom_adaptor()
                sphere = _sphere_value(surface, "Sphere")
                radius = cast("float", _sphere_value(sphere, "Radius"))
                if math.isclose(faces[0].area, 4 * math.pi * radius**2, rel_tol=1e-9):
                    center = _sphere_value(sphere, "Location")
                    anchors.append(
                        ViewportSnapAnchor(
                            "center",
                            (
                                float(cast("float", _sphere_value(center, "X"))),
                                float(cast("float", _sphere_value(center, "Y"))),
                                float(cast("float", _sphere_value(center, "Z"))),
                            ),
                            body_id,
                            self._face_topology_id(snapshot.geometry_revision, body_index, 0),
                        )
                    )
            for edge_index, edge in enumerate(solid.edges()):
                identity = self._boundary_topology_id(
                    snapshot.geometry_revision, body_index, edge_index
                )
                if identity not in visible_edges:
                    continue
                if edge.geom_type == GeomType.CIRCLE:
                    center = edge.arc_center
                    anchors.append(
                        ViewportSnapAnchor(
                            "center",
                            (float(center.X), float(center.Y), float(center.Z)),
                            body_id,
                            identity,
                        )
                    )
                if edge.is_closed or not math.isfinite(edge.length) or edge.length <= 0:
                    continue
                try:
                    point = edge.position_at(float(edge.length) / 2.0, PositionMode.LENGTH)
                except (ValueError, RuntimeError):
                    continue
                anchors.append(
                    ViewportSnapAnchor(
                        "midpoint",
                        (float(point.X), float(point.Y), float(point.Z)),
                        body_id,
                        identity,
                    )
                )
        return tuple(anchors)

    def sketch_display_data(self) -> tuple[ViewportSketchData, ...]:
        """Return backend-neutral world-space polylines for visible sketches."""
        from mycad.geom.sketch_constraints import sketch_dimension_anchor

        result: list[ViewportSketchData] = []
        for sketch in self._sketches.values():
            curves: list[ViewportSketchCurve] = []
            dimensions: list[ViewportSketchDimension] = []
            sketch_points: list[ViewportSketchPoint] = []
            for entity in sketch.entities:
                layer = sketch.layers.get(entity.layer_name)
                if layer.frozen:
                    continue
                if isinstance(entity, PointEntity):
                    if layer.visible:
                        sketch_points.append(
                            ViewportSketchPoint(
                                entity.entity_id,
                                sketch.frame.local_to_world(entity.position_mm),
                                layer,
                            )
                        )
                    continue
                if isinstance(entity, LineEntity):
                    local_points = (entity.start_mm, entity.end_mm)
                elif isinstance(entity, SplineEntity | EllipseEntity):
                    local_points = entity.sampled_points()
                elif isinstance(entity, PolylineEntity):
                    local_points = polyline_sampled_points(entity)
                elif isinstance(entity, RectangleEntity):
                    first_u, first_v = entity.first_corner_mm
                    opposite_u, opposite_v = entity.opposite_corner_mm
                    local_points = (
                        (first_u, first_v),
                        (opposite_u, first_v),
                        (opposite_u, opposite_v),
                        (first_u, opposite_v),
                        (first_u, first_v),
                    )
                else:
                    segments = (
                        48
                        if isinstance(entity, CircleEntity)
                        else max(12, math.ceil(abs(entity.sweep_angle_deg) / 7.5))
                    )
                    start_angle = (
                        0.0 if isinstance(entity, CircleEntity) else entity.start_angle_deg
                    )
                    sweep_angle = (
                        360.0 if isinstance(entity, CircleEntity) else entity.sweep_angle_deg
                    )
                    local_points = tuple(
                        (
                            entity.center_mm[0]
                            + entity.radius_mm
                            * math.cos(math.radians(start_angle + sweep_angle * index / segments)),
                            entity.center_mm[1]
                            + entity.radius_mm
                            * math.sin(math.radians(start_angle + sweep_angle * index / segments)),
                        )
                        for index in range(segments + 1)
                    )
                if not layer.visible:
                    continue
                curves.append(
                    ViewportSketchCurve(
                        entity_id=entity.entity_id,
                        points=tuple(sketch.frame.local_to_world(point) for point in local_points),
                        construction=entity.construction,
                        layer=layer,
                    )
                )
            for constraint in sketch.constraints:
                if constraint.kind not in DIMENSION_KINDS or constraint.value is None:
                    continue
                try:
                    entity = next(
                        item
                        for item in sketch.entities
                        if item.entity_id == constraint.references[0].entity_id
                    )
                    layer = sketch.layers.get(constraint.layer_name or entity.layer_name)
                    if not layer.displayed:
                        continue
                    anchor = sketch_dimension_anchor(
                        sketch, constraint, offset_mm=5.0 * constraint.scale
                    )
                except (StopIteration, ValueError):
                    continue
                value_text = f"{constraint.value:.{constraint.precision}f}"
                if constraint.kind == "angle":
                    text = f"{value_text}°"
                elif constraint.kind == "radius":
                    text = f"R{value_text} mm"
                elif constraint.kind == "diameter":
                    text = f"⌀{value_text} mm"
                else:
                    text = f"{value_text} mm"
                dimensions.append(
                    ViewportSketchDimension(
                        constraint.constraint_id,
                        text,
                        sketch.frame.local_to_world(anchor),
                        layer.color_rgb,
                        constraint.scale,
                    )
                )
            result.append(
                ViewportSketchData(
                    sketch.sketch_id, tuple(curves), tuple(dimensions), tuple(sketch_points)
                )
            )
        return tuple(result)

    @property
    def geometry_revision(self) -> int:
        """Monotonic revision for measurement and selection invalidation."""

        return self._geometry_revision

    @property
    def feature_ids(self) -> tuple[FeatureId, ...]:
        """Runtime identities of geometry/sketch results; drawing-only checkpoints add none."""

        return tuple(self._feature_ids)

    @property
    def body_ids(self) -> tuple[BodyId, ...]:
        """Runtime identities for current solids, independent of history snapshots."""

        return self._body_ids

    def interactive_body_selector(self, identity: BodyId) -> dict[str, object]:
        """Convert a current viewport body pick into a replayable geometry locator."""

        try:
            index = self._body_ids.index(identity)
        except ValueError as exc:
            raise TopologyReferenceError(
                "reason=drift: selected body is no longer current",
                reason="drift",
            ) from exc
        return body_selector_for_index(self._part, index)

    def is_current_topology(self, identity: TopologyId) -> bool:
        """Whether a viewport or semantic topology ID is still live."""
        return self._identity_scope.is_current_topology(identity)

    def _boundary_topology_id(self, revision: int, body_index: int, edge_index: int) -> TopologyId:
        key = (revision, body_index, edge_index)
        identity = self._boundary_topology_ids.get(key)
        if identity is None:
            identity = self._identity_scope.new_topology_id()
            self._boundary_topology_ids[key] = identity
        return identity

    def _viewport_boundary_edges(
        self,
        part: Part | None,
        body_ids: tuple[BodyId, ...],
        revision: int,
        linear_tolerance_mm: float,
    ) -> tuple[ViewportBoundaryEdge, ...]:
        return build_boundary_edges(
            part,
            body_ids,
            lambda body_index, edge_index: self._boundary_topology_id(
                revision, body_index, edge_index
            ),
            linear_tolerance_mm,
        )

    def _face_topology_id(self, revision: int, body_index: int, face_index: int) -> TopologyId:
        key = (revision, body_index, face_index)
        identity = self._face_topology_ids.get(key)
        if identity is None:
            identity = self._identity_scope.new_topology_id()
            self._face_topology_ids[key] = identity
        return identity

    def _vertex_topology_id(self, revision: int, body_index: int, vertex_index: int) -> TopologyId:
        key = (revision, body_index, vertex_index)
        identity = self._vertex_topology_ids.get(key)
        if identity is None:
            identity = self._identity_scope.new_topology_id()
            self._vertex_topology_ids[key] = identity
        return identity

    def _viewport_topology(
        self,
        part: Part | None,
        body_ids: tuple[BodyId, ...],
        revision: int,
        linear_tolerance_mm: float,
        angular_tolerance_deg: float,
    ) -> ViewportTopology:
        return build_viewport_topology(
            part,
            body_ids,
            lambda body_index, face_index: self._face_topology_id(revision, body_index, face_index),
            lambda body_index, vertex_index: self._vertex_topology_id(
                revision, body_index, vertex_index
            ),
            linear_tolerance_mm,
            angular_tolerance_deg,
        )

    @property
    def current_feature_id(self) -> FeatureId | None:
        """Identity of the latest feature result, or ``None`` for empty history."""

        return self._feature_ids[-1] if self._feature_ids else None

    @property
    def last_topology_evolution(self) -> TopologyEvolution | None:
        """Operation-local evolution from the most recent successful Boolean cut."""

        return self._last_topology_evolution

    def _capture_topology_evolution(self, evolution: TopologyEvolution) -> None:
        self._pending_topology_evolution = evolution

    def bind_semantic_face(
        self,
        role: str,
        predicate: FacePredicate,
        command_id: str,
        parameter_path: str | None = None,
    ) -> tuple[SemanticFaceRef, Face]:
        """Bind a current face to the latest runtime feature identity."""

        owner = self.current_feature_id
        if owner is None:
            raise TopologyReferenceError(
                "reason=no-match: no active feature owns a face",
                command_id=command_id,
                reason="no-match",
                parameter_path=parameter_path,
            )
        return bind_semantic_face_ref(
            self._identity_scope,
            owner,
            role,
            predicate,
            self._part,
            command_id,
            parameter_path,
        )

    def resolve_semantic_face(
        self,
        reference: SemanticFaceRef,
        command_id: str,
        parameter_path: str | None = None,
    ) -> tuple[Face, TopologyResolutionEvidence]:
        """Resolve a bound face while checking active owner and generation."""

        owner = self.current_feature_id
        if owner is None:
            raise TopologyReferenceError(
                "reason=deleted: no active feature owns this face",
                command_id=command_id,
                reason="deleted",
                parameter_path=parameter_path,
            )
        return resolve_semantic_face_ref(
            self._identity_scope,
            reference,
            owner,
            self._part,
            command_id,
            parameter_path,
        )

    def bind_semantic_edge(
        self,
        role: str,
        predicate: EdgePredicate,
        command_id: str,
        parameter_path: str | None = None,
    ) -> tuple[SemanticEdgeRef, Edge]:
        """Bind a current edge to the latest runtime feature identity."""

        owner = self.current_feature_id
        if owner is None:
            raise TopologyReferenceError(
                "reason=no-match: no active feature owns an edge",
                command_id=command_id,
                reason="no-match",
                parameter_path=parameter_path,
            )
        return bind_semantic_edge_ref(
            self._identity_scope,
            owner,
            role,
            predicate,
            self._part,
            command_id,
            parameter_path,
        )

    def resolve_semantic_edge(
        self,
        reference: SemanticEdgeRef,
        command_id: str,
        parameter_path: str | None = None,
    ) -> tuple[Edge, TopologyResolutionEvidence]:
        """Resolve a bound edge while checking active owner and generation."""

        owner = self.current_feature_id
        if owner is None:
            raise TopologyReferenceError(
                "reason=deleted: no active feature owns this edge",
                command_id=command_id,
                reason="deleted",
                parameter_path=parameter_path,
            )
        return resolve_semantic_edge_ref(
            self._identity_scope,
            reference,
            owner,
            self._part,
            command_id,
            parameter_path,
        )

    def geometry_check(self) -> GeometryCheckResult:
        """Return the current exact BREP validity and volume result."""

        return validate_result(self._part, "document.current")

    def measure(self, request: MeasurementRequest) -> MeasurementResult:
        """Execute one revision-bound, exact BREP measurement."""

        descriptions: dict[MeasurementKind, tuple[str, str]] = {
            "body_volume": ("Active body volume", "mm³"),
            "cylindrical_face_diameter": ("Cylindrical face diameter", "mm"),
            "circular_edge_center_distance": ("Circular edge center distance", "mm"),
            "parallel_plane_separation": ("Parallel plane separation", "mm"),
        }
        description, unit = descriptions[request.kind]

        def failed(error: str) -> MeasurementResult:
            return MeasurementResult(
                value=None,
                unit=unit,
                revision=request.revision,
                description=description,
                error=error,
            )

        if request.revision != self._geometry_revision:
            return failed(
                f"Measurement request is stale (requested revision {request.revision}, "
                f"current revision {self._geometry_revision}); select again and retry."
            )
        if request.kind == "body_volume":
            if request.references:
                return failed("Body volume does not take face or edge references.")
            value = 0.0 if self._part is None else float(self._part.volume)
            return MeasurementResult(value, unit, request.revision, description)

        try:
            if request.kind == "cylindrical_face_diameter":
                if (
                    len(request.references) != 1
                    or type(request.references[0]) is not SemanticFaceRef
                ):
                    return failed("Select one cylindrical face.")
                reference = request.references[0]
                face, _evidence = self.resolve_semantic_face(reference, "measure")
                value = measure_cylindrical_face_diameter(face)
            elif request.kind == "circular_edge_center_distance":
                if len(request.references) != 2 or any(
                    type(reference) is not SemanticEdgeRef for reference in request.references
                ):
                    return failed("Select two circular edges.")
                first_ref, second_ref = request.references
                first_ref = cast("SemanticEdgeRef", first_ref)
                second_ref = cast("SemanticEdgeRef", second_ref)
                first, _first_evidence = self.resolve_semantic_edge(
                    first_ref, "measure", "references[0]"
                )
                second, _second_evidence = self.resolve_semantic_edge(
                    second_ref, "measure", "references[1]"
                )
                value = measure_circular_edge_center_distance(first, second)
            else:
                if len(request.references) != 2 or any(
                    type(reference) is not SemanticFaceRef for reference in request.references
                ):
                    return failed("Select two parallel planar faces.")
                first_ref, second_ref = request.references
                first_ref = cast("SemanticFaceRef", first_ref)
                second_ref = cast("SemanticFaceRef", second_ref)
                first, _first_evidence = self.resolve_semantic_face(
                    first_ref, "measure", "references[0]"
                )
                second, _second_evidence = self.resolve_semantic_face(
                    second_ref, "measure", "references[1]"
                )
                value = measure_parallel_plane_separation(first, second)
        except (TopologyReferenceError, ValueError) as exc:
            return failed(str(exc))
        return MeasurementResult(value, unit, request.revision, description)

    def measurement_targets(self, kind: MeasurementKind) -> tuple[MeasurementTarget, ...]:
        """List exact face/edge candidates the UI can bind to this revision."""

        if self._part is None:
            return ()
        targets: list[MeasurementTarget] = []
        if kind == "cylindrical_face_diameter":
            for index, face in enumerate(self._part.faces().filter_by(GeomType.CYLINDER)):
                radius = face.radius
                if radius is None:
                    continue
                center = face.center(CenterOf.MASS)
                predicate = FacePredicate(
                    surface="cylinder",
                    center_mm=(float(center.X), float(center.Y), float(center.Z)),
                    radius_mm=float(radius),
                )
                try:
                    reference, _resolved = self.bind_semantic_face(
                        f"measurement-face-{index}", predicate, "measure.select"
                    )
                except TopologyReferenceError:
                    continue
                center_text = ", ".join(f"{value:.3g}" for value in predicate.center_mm or ())
                targets.append(
                    MeasurementTarget(
                        reference, f"圆柱面 d={2.0 * float(radius):.6g} mm @ ({center_text})"
                    )
                )
        elif kind == "circular_edge_center_distance":
            anchor_keys: set[tuple[float, float, float, float]] = set()
            for face in self._part.faces().filter_by(GeomType.PLANE):
                normal = face.normal_at(face.center())
                axis = _axis_literal((normal.X, normal.Y, normal.Z))
                if axis is None:
                    continue
                parent = FacePredicate(surface="plane", axis=axis)
                for edge in face.edges():
                    if edge.geom_type != GeomType.CIRCLE:
                        continue
                    center = edge.arc_center
                    radius = edge.radius
                    anchor = (
                        float(center.X),
                        float(center.Y),
                        float(center.Z),
                        float(radius),
                    )
                    if anchor in anchor_keys:
                        continue
                    anchor_keys.add(anchor)
                    predicate = EdgePredicate(
                        parent_faces=(parent,),
                        curve="circle",
                        center_mm=anchor[:3],
                        radius_mm=anchor[3],
                    )
                    try:
                        reference, _resolved = self.bind_semantic_edge(
                            f"measurement-edge-{len(targets)}", predicate, "measure.select"
                        )
                    except TopologyReferenceError:
                        continue
                    center_text = ", ".join(f"{value:.3g}" for value in anchor[:3])
                    targets.append(
                        MeasurementTarget(
                            reference, f"圆边 d={2.0 * anchor[3]:.6g} mm @ ({center_text})"
                        )
                    )
        elif kind == "parallel_plane_separation":
            for index, face in enumerate(self._part.faces().filter_by(GeomType.PLANE)):
                normal = face.normal_at(face.center())
                axis = _axis_literal((normal.X, normal.Y, normal.Z))
                if axis is None:
                    continue
                center = face.center(CenterOf.MASS)
                predicate = FacePredicate(
                    surface="plane",
                    axis=axis,
                    center_mm=(float(center.X), float(center.Y), float(center.Z)),
                )
                try:
                    reference, _resolved = self.bind_semantic_face(
                        f"measurement-plane-{index}", predicate, "measure.select"
                    )
                except TopologyReferenceError:
                    continue
                center_text = ", ".join(f"{value:.3g}" for value in predicate.center_mm or ())
                targets.append(MeasurementTarget(reference, f"平面 {axis} @ ({center_text})"))
        return tuple(targets)

    def viewport_data(
        self,
        linear_tolerance_mm: float = DEFAULT_MESH_LINEAR_TOLERANCE_MM,
        angular_tolerance_deg: float = DEFAULT_MESH_ANGULAR_TOLERANCE_DEG,
    ) -> tuple[ViewportData, ...]:
        """Return only the current whole-model mesh, implementing ``ViewportPort``.

        Zero-argument calls keep the protocol call shape valid; the
        defaulted tolerance parameters let callers request a finer mesh
        explicitly (the kernel tessellation contract below applies).
        Repeated requests at the same geometry revision and tolerances reuse
        the immutable mesh DTO. Historical states are available through
        ``historical_viewport_data`` and are never tessellated by this read.
        Empty document → empty tuple. A successful empty result still returns
        one snapshot with an empty mesh.
        """
        if not self._snapshots:
            return ()
        state_id, revision, _snapshot_part = self._snapshots[-1]
        linear, angular = normalize_tessellation_tolerances(
            linear_tolerance_mm, angular_tolerance_deg
        )
        key: CurrentMeshCacheKey = (self._cache_generation, revision, linear, angular)
        mesh = self._current_mesh_cache.get(key)
        if mesh is None:
            mesh = build_tessellation(self._part, linear, angular)
            self._current_mesh_cache[key] = mesh
            if len(self._current_mesh_cache) > CURRENT_MESH_CACHE_MAX_ENTRIES:
                self._current_mesh_cache.popitem(last=False)
        else:
            self._current_mesh_cache.move_to_end(key)
        boundaries = self._current_boundary_cache.get(key)
        if boundaries is None:
            boundaries = self._viewport_boundary_edges(
                self._part,
                self._body_ids,
                revision,
                linear,
            )
            self._current_boundary_cache[key] = boundaries
            if len(self._current_boundary_cache) > CURRENT_MESH_CACHE_MAX_ENTRIES:
                self._current_boundary_cache.popitem(last=False)
        else:
            self._current_boundary_cache.move_to_end(key)
        topology = self._current_topology_cache.get(key)
        if topology is None:
            topology = self._viewport_topology(
                self._part,
                self._body_ids,
                revision,
                linear,
                angular,
            )
            self._current_topology_cache[key] = topology
            if len(self._current_topology_cache) > CURRENT_MESH_CACHE_MAX_ENTRIES:
                self._current_topology_cache.popitem(last=False)
        else:
            self._current_topology_cache.move_to_end(key)
        faces, vertices, triangle_face_ids, triangle_body_ids = topology
        return (
            ViewportData(
                state_id=state_id,
                mesh=mesh,
                boundary_edges=boundaries,
                geometry_revision=revision,
                vertices=vertices,
                faces=faces,
                triangle_face_ids=triangle_face_ids,
                triangle_body_ids=triangle_body_ids,
                body_origins=tuple(
                    ViewportBodyOrigin(identity, origin.result, origin.inputs)
                    for identity, origin in zip(self._body_ids, self._body_origins, strict=True)
                ),
            ),
        )

    def viewport_state_ids(self) -> tuple[str, ...]:
        """Return the historical state IDs without extracting their meshes."""

        return tuple(state_id for state_id, _revision, _part in self._snapshots)

    def historical_viewport_data(
        self,
        state_id: str,
        linear_tolerance_mm: float = DEFAULT_MESH_LINEAR_TOLERANCE_MM,
        angular_tolerance_deg: float = DEFAULT_MESH_ANGULAR_TOLERANCE_DEG,
    ) -> ViewportData | None:
        """Build or reuse one explicitly requested historical state mesh."""

        snapshot = next((item for item in self._snapshots if item[0] == state_id), None)
        if snapshot is None:
            return None
        if state_id == self._snapshots[-1][0]:
            return self.viewport_data(linear_tolerance_mm, angular_tolerance_deg)[0]
        _state_id, revision, part = snapshot
        linear, angular = normalize_tessellation_tolerances(
            linear_tolerance_mm, angular_tolerance_deg
        )
        key: HistoryMeshCacheKey = (
            self._cache_generation,
            revision,
            state_id,
            linear,
            angular,
        )
        mesh = self._history_mesh_cache.get(key)
        if mesh is None:
            mesh = build_tessellation(part, linear, angular)
            self._history_mesh_cache[key] = mesh
            if len(self._history_mesh_cache) > HISTORY_MESH_CACHE_MAX_ENTRIES:
                self._history_mesh_cache.popitem(last=False)
        else:
            self._history_mesh_cache.move_to_end(key)
        history_body_ids = self._history_body_ids.get(revision)
        if history_body_ids is None:
            solid_count = 0 if part is None else len(part.solids())
            history_body_ids = tuple(
                self._identity_scope.new_body_id() for _index in range(solid_count)
            )
            self._history_body_ids[revision] = history_body_ids
        boundaries = self._history_boundary_cache.get(key)
        if boundaries is None:
            boundaries = self._viewport_boundary_edges(part, history_body_ids, revision, linear)
            self._history_boundary_cache[key] = boundaries
            if len(self._history_boundary_cache) > HISTORY_MESH_CACHE_MAX_ENTRIES:
                self._history_boundary_cache.popitem(last=False)
        else:
            self._history_boundary_cache.move_to_end(key)
        topology = self._history_topology_cache.get(key)
        if topology is None:
            topology = self._viewport_topology(
                part,
                history_body_ids,
                revision,
                linear,
                angular,
            )
            self._history_topology_cache[key] = topology
            if len(self._history_topology_cache) > HISTORY_MESH_CACHE_MAX_ENTRIES:
                self._history_topology_cache.popitem(last=False)
        else:
            self._history_topology_cache.move_to_end(key)
        faces, vertices, triangle_face_ids, triangle_body_ids = topology
        return ViewportData(
            state_id=state_id,
            mesh=mesh,
            boundary_edges=boundaries,
            geometry_revision=revision,
            vertices=vertices,
            faces=faces,
            triangle_face_ids=triangle_face_ids,
            triangle_body_ids=triangle_body_ids,
        )

    def mass_properties(self) -> MassProperties:
        """Measure the current solid; empty geometry yields zeros, not errors."""

        return build_mass_properties(self._part)

    def tessellate(self, linear_tolerance_mm: float, angular_tolerance_deg: float) -> Tessellation:
        """Triangulate the current solid into in-memory vertex/index data.

        Writes no file format and touches no rendering stack. A finer
        (halved) linear tolerance must yield a strictly greater triangle
        count wherever the linear deflection is the binding constraint.
        """

        return build_tessellation(self._part, linear_tolerance_mm, angular_tolerance_deg)

    def export_step(self, path: str | Path) -> None:
        """Write the current model as a STEP file (wired by T8 via geom.io)."""

        write_step(self._part, Path(path))

    def export_stl(self, path: str | Path) -> None:
        """Write the current model as an STL mesh (wired by T8 via geom.io)."""

        write_stl(self._part, Path(path))

    def face_candidates(
        self,
        selector: FaceSelector | Mapping[str, object],
        command_id: str,
    ) -> list[Face]:
        """All faces matching the selector, in the deterministic total order."""

        return ordered_face_candidates(selector, self._part, command_id)

    def interactive_face_selector(self, identity: TopologyId) -> dict[str, object]:
        """Convert a current viewport face identity to a replayable geometric locator."""

        self._identity_scope.require_current_topology(identity)
        key = next(
            (
                candidate
                for candidate, candidate_id in self._face_topology_ids.items()
                if candidate_id == identity
            ),
            None,
        )
        if key is None or key[0] != self._geometry_revision or self._part is None:
            raise TopologyReferenceError("reason=drift: selected face is no longer current")
        _revision, body_index, face_index = key
        solids = self._part.solids()
        if body_index >= len(solids) or face_index >= len(solids[body_index].faces()):
            raise TopologyReferenceError("reason=drift: selected face identity is out of range")
        face = solids[body_index].faces()[face_index]
        descriptor = self._interactive_face_descriptor(face)
        candidates = ordered_face_candidates(descriptor, self._part, "interactive-selection")
        rank = next(
            (index for index, candidate in enumerate(candidates) if candidate == face), None
        )
        if rank is None:
            raise TopologyReferenceError("reason=drift: selected face anchor no longer resolves")
        if len(candidates) > 1:
            descriptor["rank"] = rank
        return descriptor

    def interactive_face_binding(self, identity: TopologyId) -> dict[str, object]:
        """Mint a design reference from an exact current, locally owned face pick."""
        self._identity_scope.require_current_topology(identity, "feature.hole", "target_face")
        key = next((k for k, value in self._face_topology_ids.items() if value == identity), None)
        if key is None or key[0] != self._geometry_revision or self._part is None:
            raise TopologyReferenceError(
                "face pick is no longer current",
                command_id="feature.hole",
                reason="drift",
                parameter_path="target_face",
            )
        _revision, body_index, face_index = key
        face = self._part.solids()[body_index].faces()[face_index]
        return self._design_faces.reference_for(face).to_mapping()

    def interactive_bound_face_frame(self, identity: TopologyId) -> WorkPlaneFrame:
        """Return the design-local frame of a uniquely bound current face."""
        binding = BoundFaceRef.from_mapping(self.interactive_face_binding(identity))
        return self._design_faces.frame_for(binding)

    def interactive_face_frame(self, identity: TopologyId) -> PlanarFaceFrame:
        """Expose exact planar geometry without leaking a backend shape to the UI."""
        selector = self.interactive_face_selector(identity)
        face = resolve_face(selector, self._part, "interactive-face-frame")
        if face.geom_type != GeomType.PLANE:
            raise TopologyReferenceError("请选择平面；曲面没有唯一的拉伸方向。")
        origin = face.center()
        normal = face.normal_at().normalized()
        return PlanarFaceFrame(
            (float(origin.X), float(origin.Y), float(origin.Z)),
            (float(normal.X), float(normal.Y), float(normal.Z)),
        )

    def interactive_edge_selector(self, identity: TopologyId) -> dict[str, object]:
        """Convert a current viewport edge identity to a precise replayable locator."""

        self._identity_scope.require_current_topology(identity)
        key = next(
            (
                candidate
                for candidate, candidate_id in self._boundary_topology_ids.items()
                if candidate_id == identity
            ),
            None,
        )
        if key is None or key[0] != self._geometry_revision or self._part is None:
            raise TopologyReferenceError("reason=drift: selected edge is no longer current")
        _revision, body_index, edge_index = key
        solids = self._part.solids()
        if body_index >= len(solids) or edge_index >= len(solids[body_index].edges()):
            raise TopologyReferenceError("reason=drift: selected edge identity is out of range")
        edge = solids[body_index].edges()[edge_index]
        if edge.geom_type not in (GeomType.LINE, GeomType.CIRCLE):
            raise TopologyReferenceError(
                f"reason=unsupported-curve: selected {edge.geom_type.name.lower()} edge "
                "cannot be used by the current fillet selector"
            )
        parent = next(
            (face for face in self._part.faces() if edge in face.edges()),
            None,
        )
        if parent is None:
            raise TopologyReferenceError("reason=drift: selected edge has no current parent face")
        parent_locator = self._interactive_face_descriptor(parent)
        center = edge.arc_center if edge.geom_type == GeomType.CIRCLE else edge.center()
        descriptor: dict[str, object] = {
            "parent_faces": [parent_locator],
            "curve": "circle" if edge.geom_type == GeomType.CIRCLE else "line",
            "center_mm": [float(center.X), float(center.Y), float(center.Z)],
        }
        if edge.geom_type == GeomType.CIRCLE:
            descriptor["radius_mm"] = float(edge.radius)
        return descriptor

    @staticmethod
    def _interactive_face_descriptor(face: Face) -> dict[str, object]:
        """Build a center-anchored face mapping without exposing a BREP object."""

        if face.geom_type == GeomType.PLANE:
            normal = face.normal_at(face.center())
            axis = _axis_literal((float(normal.X), float(normal.Y), float(normal.Z)))
            descriptor: dict[str, object] = {"surface": "plane"}
            if axis is not None:
                descriptor["axis"] = axis
        elif face.geom_type == GeomType.CYLINDER:
            descriptor = {"surface": "cylinder"}
            if face.axis_of_rotation is not None:
                direction = face.axis_of_rotation.direction
                axis = _axis_literal((float(direction.X), float(direction.Y), float(direction.Z)))
                if axis is not None:
                    descriptor["axis"] = axis
            if face.radius is not None:
                descriptor["radius_mm"] = float(face.radius)
        else:
            raise TopologyReferenceError(
                f"reason=unsupported-surface: selected {face.geom_type.name.lower()} face "
                "cannot be used by the current modeling selector"
            )
        center = face.center(CenterOf.MASS)
        descriptor["center_mm"] = [float(center.X), float(center.Y), float(center.Z)]
        return descriptor

    def resolve_face(
        self,
        selector: FaceSelector | Mapping[str, object],
        command_id: str,
    ) -> Face:
        """Resolve a FaceSelector to exactly one face (rank/unique semantics)."""

        return resolve_face(selector, self._part, command_id)

    def resolve_edges(
        self,
        selector: EdgeSelector | Mapping[str, object],
        command_id: str,
    ) -> list[Edge]:
        """Resolve an EdgeSelector to its ordered edge list."""

        return resolve_edges(selector, self._part, command_id)
