# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Viewport port: the third dependency inversion (phase 1, todo 2).

Core holds only ``ViewportData`` and the ``ViewportPort`` Protocol; it
never imports ``mycad.geom``, ``numpy`` or Qt. The concrete current mesh,
sampled BREP boundary records, and explicitly requested historical preview
are implemented by the BuildKernel adapter in ``mycad.geom`` and consumed
by the UI package. Rendering semantics (colours and lights) stay out of core.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast, runtime_checkable

from mycad.core.geometry_types import Tessellation
from mycad.core.identity import BodyId, TopologyId
from mycad.core.sketch import WorkPlaneFrame
from mycad.core.sketch_layers import DEFAULT_SKETCH_LAYER, SketchLayer
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_references import SpatialReference

Point3 = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class ViewportSketchRegion:
    """Display mesh for a sketch region identified by its authored outer contour."""

    boundary_entity_ids: tuple[str, ...]
    mesh: Tessellation
    hole_entity_ids: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class ViewportDatum:
    """Persistent spatial output and its evaluated world-space frame."""

    reference: SpatialReference
    name: str
    frame: RigidFrame | WorkPlaneFrame

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("datum display requires a name")
        if self.reference.kind == "coordinate_system" and isinstance(self.frame, RigidFrame):
            return
        if self.reference.kind == "datum_plane" and isinstance(self.frame, WorkPlaneFrame):
            return
        raise ValueError("datum reference and evaluated frame must have matching types")


@dataclass(frozen=True, slots=True)
class ViewportSnapAnchor:
    """Exact current BREP anchor with its runtime object ownership."""

    kind: Literal["vertex", "midpoint", "center"]
    point: Point3
    body_id: BodyId | None
    topology_id: TopologyId | None
    source_key: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("vertex", "midpoint", "center"):
            raise ValueError("invalid snap anchor kind")
        if len(self.point) != 3 or any(not math.isfinite(value) for value in self.point):
            raise ValueError("snap anchor coordinates must be finite")
        if self.topology_id is None and not self.source_key:
            raise ValueError("snap anchor requires an object identity")


@dataclass(frozen=True, slots=True)
class CandidateInteractionScene:
    """Display and pick data for one source-bound candidate generation."""

    document_id: str
    file_id: str
    revision: int
    session_identity: int
    candidate_id: str
    generation: int
    viewport: ViewportData | None
    sketches: tuple[ViewportSketchData, ...]
    datums: tuple[ViewportDatum, ...]
    snap_anchors: tuple[ViewportSnapAnchor, ...]

    def matches(
        self, document_id: str, revision: int, session: int, candidate_id: str, generation: int
    ) -> bool:
        return (
            self.document_id == document_id
            and self.revision == revision
            and self.session_identity == session
            and self.candidate_id == candidate_id
            and self.generation == generation
        )


@runtime_checkable
class SpatialDatumPort(Protocol):
    """Evaluated datums independently of solid mesh availability."""

    def datum_display_data(self) -> tuple[ViewportDatum, ...]: ...

    def snap_anchor_data(self) -> tuple[ViewportSnapAnchor, ...]: ...


@dataclass(frozen=True, slots=True)
class PlanarFaceFrame:
    """Exact model-space anchor and outward unit normal for a face manipulator."""

    origin: Point3
    normal: Point3


@dataclass(frozen=True, slots=True)
class ViewportBoundaryEdge:
    """Sampled display polyline for one revision-bound BREP boundary edge."""

    topology_id: TopologyId
    body_id: BodyId
    points: tuple[Point3, ...]

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("boundary edge requires at least two points")
        for point in self.points:
            if len(point) != 3 or any(
                isinstance(value, bool) or not math.isfinite(value) for value in point
            ):
                raise ValueError("boundary edge points must contain finite coordinates")


@dataclass(frozen=True, slots=True)
class ViewportVertex:
    """Runtime-identified exact BREP vertex used by screen-space selection."""

    topology_id: TopologyId
    body_id: BodyId
    point: Point3

    def __post_init__(self) -> None:
        if len(self.point) != 3 or any(
            isinstance(value, bool) or not math.isfinite(value) for value in self.point
        ):
            raise ValueError("viewport vertex point must contain finite coordinates")


@dataclass(frozen=True, slots=True)
class ViewportFace:
    """Runtime-identified exact BREP face used by triangle selection."""

    topology_id: TopologyId
    body_id: BodyId


@dataclass(frozen=True, slots=True)
class ViewportSketchCurve:
    """World-space polyline for one visible sketch entity."""

    entity_id: str
    points: tuple[Point3, ...]
    construction: bool = False
    layer: SketchLayer = DEFAULT_SKETCH_LAYER

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("sketch display curve requires at least two points")
        if not self.entity_id:
            raise ValueError("sketch display curve requires an entity identity")
        if not isinstance(cast("object", self.construction), bool):
            raise ValueError("sketch display curve construction flag must be boolean")
        for point in self.points:
            if len(point) != 3 or any(
                isinstance(value, bool) or not math.isfinite(value) for value in point
            ):
                raise ValueError("sketch display points must contain finite coordinates")


@dataclass(frozen=True, slots=True)
class ViewportSketchDimension:
    """Screen-readable label for one durable sketch dimension annotation."""

    constraint_id: str
    text: str
    position: Point3
    color_rgb: tuple[int, int, int]
    scale: float = 1.0

    def __post_init__(self) -> None:
        if not self.constraint_id or not self.text:
            raise ValueError("sketch dimension needs a stable ID and visible text")
        if len(self.position) != 3 or any(
            isinstance(value, bool)
            or not isinstance(cast("object", value), int | float)
            or not math.isfinite(value)
            for value in self.position
        ):
            raise ValueError("sketch dimension position must contain finite coordinates")
        if len(self.color_rgb) != 3 or any(
            isinstance(value, bool)
            or not isinstance(cast("object", value), int)
            or not 0 <= value <= 255
            for value in self.color_rgb
        ):
            raise ValueError("sketch dimension color must be an RGB byte triple")
        if (
            isinstance(self.scale, bool)
            or not isinstance(cast("object", self.scale), int | float)
            or not math.isfinite(self.scale)
            or self.scale <= 0.0
        ):
            raise ValueError("sketch dimension scale must be positive and finite")


@dataclass(frozen=True, slots=True)
class ViewportSketchPoint:
    """One authored point in world coordinates for screen-sized display."""

    entity_id: str
    point: Point3
    layer: SketchLayer = DEFAULT_SKETCH_LAYER

    def __post_init__(self) -> None:
        if (
            not self.entity_id
            or len(self.point) != 3
            or any(isinstance(value, bool) or not math.isfinite(value) for value in self.point)
        ):
            raise ValueError("sketch display point requires identity and finite coordinates")


@dataclass(frozen=True, slots=True)
class ViewportSketchData:
    """Sketch curves rendered as a non-pickable overlay over the model."""

    sketch_id: str
    curves: tuple[ViewportSketchCurve, ...]
    dimensions: tuple[ViewportSketchDimension, ...] = ()
    points: tuple[ViewportSketchPoint, ...] = ()

    def __post_init__(self) -> None:
        if not self.sketch_id:
            raise ValueError("viewport sketch requires a sketch identity")


BodyInputRole = Literal["target", "tool", "seed", "source", "model"]


@dataclass(frozen=True, slots=True)
class BodyResultReference:
    """A solid result in a historical state; independent of runtime identities."""

    state_id: str
    solid_index: int

    def __post_init__(self) -> None:
        if not self.state_id:
            raise ValueError("body result requires a state identity")
        if (
            isinstance(self.solid_index, bool)
            or not isinstance(cast("object", self.solid_index), int)
            or self.solid_index < 0
        ):
            raise ValueError("body result index must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class BodyOperationInput:
    """A step input, not a claim of face-level geometric ancestry."""

    role: BodyInputRole
    result: BodyResultReference

    def __post_init__(self) -> None:
        if self.role not in ("target", "tool", "seed", "source", "model"):
            raise ValueError("unknown body operation input role")


@dataclass(frozen=True, slots=True)
class ViewportBodyOrigin:
    body_id: BodyId
    result: BodyResultReference
    inputs: tuple[BodyOperationInput, ...] = ()


@dataclass(frozen=True)
class ViewportData:
    """One whole-model state snapshot, in feature-history order.

    ``state_id`` identifies the post-command state as
    ``"<command id>:<ordinal>"`` (snapshot semantics are implemented by the
    geom adapter in todo 3). It is a state identifier, not a face/edge/solid
    identity or a mapping from hit geometry back to its source feature.
    ``mesh`` reuses ``mycad.core.geometry_types.Tessellation`` verbatim —
    vertex/index invariants are validated in its own ``__post_init__``,
    and the vertex/index fields are deliberately NOT redefined here so
    the DTO keeps a single definition point. ``normals`` is optional:
    the UI may derive or compute them when a visual style needs them.
    """

    state_id: str
    mesh: Tessellation
    normals: tuple[tuple[float, float, float], ...] = field(default=())
    boundary_edges: tuple[ViewportBoundaryEdge, ...] = field(default=())
    geometry_revision: int = 0
    vertices: tuple[ViewportVertex, ...] = field(default=())
    faces: tuple[ViewportFace, ...] = field(default=())
    triangle_face_ids: tuple[TopologyId, ...] = field(default=())
    triangle_body_ids: tuple[BodyId, ...] = field(default=())
    body_origins: tuple[ViewportBodyOrigin, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.geometry_revision, bool) or self.geometry_revision < 0:
            raise ValueError("geometry revision must be a nonnegative integer")
        triangle_count = len(self.mesh.triangle_indices)
        if (
            len(self.triangle_face_ids) != triangle_count
            or len(self.triangle_body_ids) != triangle_count
        ):
            raise ValueError("triangle identity arrays must match mesh triangle count")
        known_face_ids = {face.topology_id for face in self.faces}
        if not set(self.triangle_face_ids) <= known_face_ids:
            raise ValueError("triangle face identity must refer to a viewport face")
        known_body_ids = {face.body_id for face in self.faces}
        if not set(self.triangle_body_ids) <= known_body_ids:
            raise ValueError("triangle body identity must refer to a viewport face body")
        if self.body_origins:
            origin_ids = {origin.body_id for origin in self.body_origins}
            if len(origin_ids) != len(self.body_origins) or origin_ids != known_body_ids:
                raise ValueError("body origins must uniquely cover the current viewport bodies")
        if len(known_face_ids) != len(self.faces):
            raise ValueError("viewport face topology identities must be unique")
        if len({vertex.topology_id for vertex in self.vertices}) != len(self.vertices):
            raise ValueError("viewport vertex topology identities must be unique")


@runtime_checkable
class ViewportPort(Protocol):
    """Current mesh plus lightweight access to on-demand history previews."""

    def viewport_data(self) -> tuple[ViewportData, ...]:
        """Return the current whole-model mesh, or an empty tuple.

        A geometry command that removes all geometry still returns one
        snapshot with an empty mesh. Historical meshes are intentionally not
        part of this request so ordinary refresh does not tessellate history.
        """
        ...

    def viewport_state_ids(self) -> tuple[str, ...]:
        """Return lightweight post-command history IDs in feature order."""
        ...

    def sketch_display_data(self) -> tuple[ViewportSketchData, ...]:
        """Return current sketch curves independently from solid mesh snapshots."""
        ...

    def historical_viewport_data(self, state_id: str) -> ViewportData | None:
        """Return one requested post-command state mesh, if it still exists."""
        ...
