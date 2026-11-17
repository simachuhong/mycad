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
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.document_references import DocumentReference
from mycad.core.drawing import DrawingState
from mycad.core.drawing_codec import apply_drawing_command
from mycad.core.drawing_detail import clip_detail_projection
from mycad.core.drawing_projection import (
    DrawingProjectionRequest,
    DrawingSourceSnapshot,
    ProjectionResult,
    ViewBasis,
)
from mycad.core.drawing_quick_regions import SampledMeasuredRegion
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.exceptions import (
    GeometryBuildError,
    GeomVersionError,
    MycadError,
    TopologyReferenceError,
    ValidationError,
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
        self._drawing_fillet_baseline = candidate._drawing_fillet_baseline
        self._drawing_fillet_radius = candidate._drawing_fillet_radius
        self._drawing_chamfer_angle_baseline = candidate._drawing_chamfer_angle_baseline
        self._drawing_chamfer_values = candidate._drawing_chamfer_values
        self._drawing_state = candidate._drawing_state
        self._drawing_rasters = dict(candidate._drawing_rasters)
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
        if command_id == "drawing.raster.batch":
            try:
                action = checked.get("action")
                candidate = dict(self._drawing_rasters)
                seen: set[str] = set()
                if action == "remove":
                    for identity in cast("list[str]", checked["image_ids"]):
                        if identity in seen or identity not in candidate:
                            raise ValueError("图片不存在或身份重复。")
                        seen.add(identity)
                        del candidate[identity]
                else:
                    for value in cast("list[object]", checked["images"]):
                        image = DrawingRaster.from_mapping(value)
                        identity = image.image_id
                        if identity in seen or ((identity in candidate) != (action == "update")):
                            raise ValueError("图片身份重复或不存在。")
                        seen.add(identity)
                        self.drawing_layers.get(image.layer_name)
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
                if command_id == "drawing.raster.remove":
                    del self._drawing_rasters[identity]
                else:
                    image = DrawingRaster.from_mapping(dict(checked))
                    self.drawing_layers.get(image.layer_name)
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
                styles = DimensionStyleTable.from_mapping(checked["clipboard_styles"])
                previous = self._drawing_dimension_styles
                if styles.current_name != previous.current_name or any(
                    styles.get(style.name) != style for style in previous.styles
                ):
                    raise ValueError("粘贴时不能更改现有标注样式。")
            except (KeyError, ValueError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            self._set_drawing_layers(checked)
            self._drawing_dimension_styles = styles
            return
        if command_id == "drawing.dimension_styles.set":
            try:
                table = DimensionStyleTable.from_mapping(checked)
                updated: dict[str, Sketch] = {}
                for identity, sketch in self._sketches.items():
                    constraints: list[SketchConstraint] = []
                    for constraint in sketch.constraints:
                        if constraint.style_name is None:
                            constraints.append(constraint)
                            continue
                        style = table.get(constraint.style_name)
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
                        create_layers.get(image.layer_name)
                        create_rasters[image.image_id] = image
                except (TypeError, ValueError, KeyError) as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
            previous_styles = self._drawing_dimension_styles
            if "clipboard_styles" in checked:
                try:
                    styles = DimensionStyleTable.from_mapping(checked["clipboard_styles"])
                    if styles.current_name != previous_styles.current_name or any(
                        styles.get(style.name) != style for style in previous_styles.styles
                    ):
                        raise ValueError("粘贴时不能更改现有标注样式。")
                except (KeyError, ValueError) as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
                self._drawing_dimension_styles = styles
            sketch_params = {
                key: value
                for key, value in checked.items()
                if key not in ("raster_batch", "clipboard_styles")
            }
            try:
                if "cross_tangencies" in sketch_params or "associative_arrays" in sketch_params:
                    self._create_sketch_with_cross_tangencies(sketch_params)
                else:
                    self._create_sketch(sketch_params)
            except Exception:
                self._drawing_dimension_styles = previous_styles
                raise
            if create_rasters is not None:
                self._drawing_rasters = create_rasters
            return
        if command_id == "drawing.sketch.revise":
            revisions = cast("list[Mapping[str, object]]", checked["revisions"])
            raster_candidate: dict[str, DrawingRaster] | None = None
            if "raster_batch" in checked:
                try:
                    batch = cast("Mapping[str, object]", checked["raster_batch"])
                    action = batch["action"]
                    raster_candidate = dict(self._drawing_rasters)
                    revision_seen: set[str] = set()
                    if action == "remove":
                        for identity in cast("list[str]", batch["image_ids"]):
                            if identity in revision_seen or identity not in raster_candidate:
                                raise ValueError("图片不存在或身份重复。")
                            revision_seen.add(identity)
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
                            self.drawing_layers.get(image.layer_name)
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
                    )
                except (TypeError, ValueError) as exc:
                    raise ValidationError(str(exc), command_id=command_id) from exc
            else:
                ids = [revision["sketch_id"] for revision in revisions]
                if len(set(ids)) != len(ids):
                    raise ValidationError("duplicate sketch revision", command_id=command_id)
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
        self._sketches = sketches
        self._record_sketch_change(command_id)

    def _prepare_sketch_revision(
        self,
        params: Mapping[str, object],
        *,
        dimension: SketchConstraint | None = None,
        rectangle_transforms: Sequence[RectangleTransformEvidence] = (),
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
            self._validate_dimension_style_references(revised.constraints, "sketch.revise")
            old_entities = {item.entity_id: item for item in current.entities}
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
                    current, revised, tuple(rectangle_transforms)
                )
                if supports_local_rebind and rectangle_transforms
                else current.constraints
            )
            expected_by_id = {item.constraint_id: item for item in expected_constraints}
            retained_local = {}
            if (
                context is not None
                and context.command_id == "drawing.sketch.revise"
                and context.command_version >= 41
            ):
                retained_local = {
                    item.constraint_id: item
                    for item in rebind_retained_local_tangencies(
                        current,
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
        self, sketches: Mapping[str, Sketch], command_id: str
    ) -> dict[str, Sketch]:
        if not self._associative_arrays:
            return dict(sketches)
        try:
            result = propagate_array_changes(
                tuple(self._sketches.values()), tuple(sketches.values()), self.associative_arrays
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        updated = {sketch.sketch_id: sketch for sketch in result}
        self._validate_array_cross_changes(updated, command_id)
        return updated

    def _validate_array_cross_changes(self, updated: Mapping[str, Sketch], command_id: str) -> None:
        try:
            validate_array_cross_changes(
                self._sketches, updated, self.associative_arrays, self.cross_sketch_tangencies
            )
        except (KeyError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc

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
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(command_id)

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
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {array.array_id: array for array in arrays}
        self._record_sketch_change(command_id)

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
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(command_id)

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
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(command_id)

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
            self._validate_array_cross_changes(sketches, command_id)
            self._validate_cross_tangencies(sketches, self._cross_tangencies)
            candidate = self._regenerate_with_sketches(sketches)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(str(exc), command_id=command_id) from exc
        self._sketches = candidate._sketches
        self._associative_arrays = {**self._associative_arrays, updated.array_id: updated}
        self._record_sketch_change(command_id)

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
            )
            for revision in revisions
        )
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
            sketches = self._propagate_associative_arrays(sketches, command_id)
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
        verified_transform_relations: set[str] = set()
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
                referenced = {
                    (ref.sketch_id, ref.entity_id)
                    for item in affected
                    for ref in (item.first, item.second)
                    if (ref.sketch_id, ref.entity_id) in keys
                }
                local_only = {
                    (sketch.sketch_id, ref.entity_id)
                    for sketch in self._sketches.values()
                    for constraint in sketch.constraints
                    for ref in constraint.references
                    if (sketch.sketch_id, ref.entity_id) in keys
                }
                context = self._active_execution_context
                supports_local_only = (
                    context is not None
                    and context.command_id == "drawing.sketch.revise"
                    and context.command_version >= 30
                )
                if referenced != keys and not (
                    supports_local_only and referenced | local_only == keys
                ):
                    raise ValueError("矩形变换依据没有关联的相切关系。")
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
        if record:
            self._record_sketch_change(command_id)

    def _apply_cross_tangency(self, params: Mapping[str, object]) -> None:
        try:
            relation = CrossSketchTangency.from_mapping(params.get("relation"))
            revisions = params.get("revisions")
            if not isinstance(revisions, list | tuple):
                raise ValueError("跨草图相切修订必须是数组。")
            values = cast("Sequence[object]", revisions)
            if any(not isinstance(item, Mapping) for item in values):
                raise ValueError("跨草图相切修订必须是数组。")
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
                candidate._record_sketch_change(command_id)
                continue
            try:
                replay_params = (
                    {
                        key: value
                        for key, value in params.items()
                        if key not in ("cross_tangencies", "associative_arrays")
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
        candidate._dimension_layer = self._dimension_layer
        candidate._drawing_dimension_styles = self._drawing_dimension_styles
        candidate._drawing_fillet_radius = self._drawing_fillet_radius
        candidate._drawing_chamfer_values = self._drawing_chamfer_values
        candidate._cross_tangencies = dict(self._cross_tangencies)
        candidate._associative_arrays = dict(self._associative_arrays)
        return candidate

    def _record_sketch_change(self, command_id: str) -> None:
        """Invalidate model-dependent views and append a replay snapshot."""
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
            if constraint.style_name is None:
                continue
            try:
                style = self._drawing_dimension_styles.get(constraint.style_name)
            except KeyError as exc:
                raise ValidationError("尺寸引用的标注样式不存在。", command_id=command_id) from exc
            if constraint.precision != style.precision or constraint.scale != style.scale:
                raise ValidationError("尺寸格式与关联标注样式不一致。", command_id=command_id)

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
        for image in self._drawing_rasters.values():
            try:
                table.get(image.layer_name)
            except KeyError as exc:
                raise ValidationError("图层仍被图片使用，不能删除。") from exc
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
                elif isinstance(entity, SplineEntity):
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
