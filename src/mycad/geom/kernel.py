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

import importlib.metadata
import math
from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast

from build123d import CenterOf, Edge, Face, GeomType, Part

from mycad.core.drawing import DrawingState
from mycad.core.drawing_codec import apply_drawing_command
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
from mycad.core.selectors import AxisLiteral, EdgeSelector, FaceSelector
from mycad.core.semantic_refs import (
    EdgePredicate,
    FacePredicate,
    SemanticEdgeRef,
    SemanticFaceRef,
    TopologyResolutionEvidence,
)
from mycad.core.sketch import (
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import (
    DIMENSION_KINDS,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.core.sketch_layers import SketchLayerTable, merge_layer_tables
from mycad.core.viewport_protocol import (
    PlanarFaceFrame,
    ViewportBodyOrigin,
    ViewportBoundaryEdge,
    ViewportData,
    ViewportFace,
    ViewportSketchCurve,
    ViewportSketchData,
    ViewportSketchDimension,
    ViewportVertex,
)
from mycad.geom._b123_features import (
    apply_feature,
    apply_sketch_extrusion,
    apply_sketch_hole,
    apply_sketch_revolve,
)
from mycad.geom._b123_ops import apply_primitive, checked_mapping
from mycad.geom.body_provenance import BodyOrigin, operation_origins
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


class BuildKernel:
    """Geometry kernel facade: applies feature commands to an in-memory part.

    Implements the core ``ViewportPort`` protocol structurally: every
    successful ``apply`` freezes a snapshot of the post-execution part.
    """

    def __init__(self) -> None:
        self._drawing_state = DrawingState()
        self._drawing_revision = 0
        self._part: Part | None = None
        self._snapshots: list[tuple[str, int, Part | None]] = []
        self._sketches: dict[str, Sketch] = {}
        self._drawing_layers_override: SketchLayerTable | None = None
        self._dimension_layer = "DIM"
        self._operations: list[tuple[str, dict[str, object]]] = []
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

    def reset(self) -> None:
        """Drop the current solid and the snapshot list: empty-geometry state."""
        # Snapshot list joins the cleared state: undo/redo rebuild resets the
        # kernel first, so full replay re-populates snapshots in ordinal order.

        self._part = None
        self._drawing_state = DrawingState()
        self._drawing_revision = 0
        self._snapshots = []
        self._sketches = {}
        self._drawing_layers_override = None
        self._dimension_layer = "DIM"
        self._operations = []
        self._body_origins = ()
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
        self._drawing_layers_override = candidate._drawing_layers_override
        self._dimension_layer = candidate._dimension_layer
        self._drawing_state = candidate._drawing_state
        self._drawing_revision = candidate._drawing_revision
        self._operations = deepcopy(candidate._operations)
        self._body_origins = candidate._body_origins
        self._current_mesh_cache.clear()
        self._history_mesh_cache.clear()
        self._current_boundary_cache.clear()
        self._history_boundary_cache.clear()
        self._current_topology_cache.clear()
        self._history_topology_cache.clear()

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        """Apply and retain only successful inputs for deterministic regeneration."""
        checked = checked_mapping(params, command_id)
        recorded = deepcopy(dict(checked))
        self._apply_operation(command_id, checked)
        self._operations.append((command_id, recorded))

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

        if command_id.startswith(("drawing.sheet.", "drawing.view.", "drawing.annotation.")):
            try:
                candidate_drawing = apply_drawing_command(self._drawing_state, command_id, checked)
            except (ValueError, TypeError) as exc:
                raise ValidationError(str(exc), command_id=command_id) from exc
            self._drawing_state = candidate_drawing
            self._drawing_revision += 1
            self._snapshots.append(
                (f"{command_id}:{len(self._snapshots)}", self._geometry_revision, self._part)
            )
            return
        if command_id == "drawing.layers.set":
            self._set_drawing_layers(checked)
            return
        if command_id == "sketch.create":
            self._create_sketch(checked)
            return
        if command_id in ("sketch.constraint.add", "sketch.constraint.update"):
            self._apply_sketch_constraint(checked, command_id)
            return
        sketch_profile = checked.get("profile")
        if (
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
            candidate = apply_sketch_hole(self._part, self._sketches, checked)
        elif command_id in ("feature.box", "feature.cylinder"):
            candidate = apply_primitive(self._part, command_id, checked)
        else:
            candidate = apply_feature(self._part, command_id, checked)
        requires_one_solid = (
            command_id in ("feature.box", "feature.cylinder")
            and checked.get("mode", "new") == "new"
        )
        check = validate_result(candidate, command_id, require_single_solid=requires_one_solid)
        require_valid_result(check)
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

    def _create_sketch(self, params: Mapping[str, object]) -> None:
        """Add one validated sketch projection to the Bus-replayed model state."""
        sketch = Sketch.from_mapping(params)
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
            from mycad.geom.sketch_constraints import (
                inferred_coincident_satisfied,
                measure_sketch_dimension,
            )

            try:
                for constraint in sketch.constraints:
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
        current = self._sketches.get(sketch_id) if isinstance(sketch_id, str) else None
        if current is None:
            raise ValidationError("constraint references a missing sketch", command_id=command_id)
        digest = params.get("base_state_sha256")
        if digest != current.state_digest():
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
            if rebuild_consumers:
                from mycad.geom.sketch_constraints import refresh_reference_dimensions

                updated = refresh_reference_dimensions(updated)
        except ValueError as exc:
            raise ValidationError(
                f"invalid solved sketch constraint: {exc}",
                command_id=command_id,
            ) from exc
        sketches = {**self._sketches, current.sketch_id: updated}
        if rebuild_consumers and updated.entities != current.entities:
            candidate = self._regenerate_with_sketches(sketches)
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
            self._body_origins = origins
            sketches = candidate._sketches
            count = 0 if self._part is None else len(self._part.solids())
            self._body_ids = tuple(self._identity_scope.new_body_id() for _ in range(count))
        self._sketches = sketches
        self._record_sketch_change(command_id)

    def _regenerate_with_sketches(self, sketches: Mapping[str, Sketch]) -> BuildKernel:
        """Rebuild consumers from frozen solutions without rerunning a solver.

        Constraint events were already validated against their original states.
        At each sketch's creation point install its current solved local geometry,
        keeping the support frame freshly resolved from the rebuilt upstream solid.
        The candidate stays isolated until every downstream feature succeeds.
        """
        candidate = BuildKernel()
        for operation_index, (command_id, params) in enumerate(self._operations):
            if command_id in ("sketch.constraint.add", "sketch.constraint.update"):
                continue
            if command_id == "drawing.layers.set":
                # Final sketch solutions already carry final layer assignments.
                # Preserve the history slot without applying an obsolete table.
                candidate._record_sketch_change(command_id)
                continue
            try:
                candidate._apply_operation(command_id, params)
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
        candidate._dimension_layer = self._dimension_layer
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

    @property
    def drawing_state(self) -> DrawingState:
        """Immutable engineering drawing objects reconstructed by command replay."""
        return self._drawing_state

    @property
    def drawing_revision(self) -> int:
        return self._drawing_revision

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
        self._sketches = sketches
        self._drawing_layers_override = table
        self._dimension_layer = target
        self._record_sketch_change("drawing.layers.set")

    @property
    def sketches(self) -> tuple[Sketch, ...]:
        """Immutable sketch values reconstructed from replayed commands."""
        return tuple(self._sketches.values())

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

    def sketch_display_data(self) -> tuple[ViewportSketchData, ...]:
        """Return backend-neutral world-space polylines for visible sketches."""
        from mycad.geom.sketch_constraints import sketch_dimension_anchor

        result: list[ViewportSketchData] = []
        for sketch in self._sketches.values():
            curves: list[ViewportSketchCurve] = []
            dimensions: list[ViewportSketchDimension] = []
            for entity in sketch.entities:
                layer = sketch.layers.get(entity.layer_name)
                if layer.frozen:
                    continue
                if isinstance(entity, LineEntity):
                    local_points = (entity.start_mm, entity.end_mm)
                elif isinstance(entity, SplineEntity):
                    local_points = entity.sampled_points()
                elif isinstance(entity, PolylineEntity):
                    local_points = entity.points_mm
                    if entity.closed:
                        local_points = (*local_points, local_points[0])
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
            result.append(ViewportSketchData(sketch.sketch_id, tuple(curves), tuple(dimensions)))
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
