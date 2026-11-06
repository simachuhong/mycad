# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo 9: the 3D viewport — a pyqtgraph.opengl surface fed by the kernel.

The default scene shows exactly ONE snapshot: the whole-model state after
the last executed command (``viewport_data()[-1]``), drawn as one shaded
MeshData plus sampled BREP boundary edges. Triangle edges are an explicit
diagnostic mode. Ray picking uses only the current snapshot and selects the
result as a whole; it never guesses a historical feature source. Clicking a
feature row explicitly replaces the scene with that post-command historical
state. A separate action returns to the current model, so removed geometry
is never overlaid on the current view.

Refresh subscribes only to geometry-affecting core signals: commands emit
``post_command``, undo/redo/replay/rollback emit ``geometry_rebuilt``, and
edit-and-replay emits ``command_amended``. Metadata and named-group signals
do not change viewport data. The geometry signals converge on
``_schedule_refresh()``, which coalesces a whole event-loop turn into one
rebuild — a batch renders its final snapshot exactly once.

No ``mycad.geom`` import: geometry arrives through the core ``ViewportPort``
protocol, so this module never touches the CAD backend (tests/test_layering
bans it) and stays on the data side of the boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from math import atan, cos, dist, radians, sin, tan
from time import monotonic
from typing import TYPE_CHECKING, Literal, Protocol, cast, override

import numpy as np
from pyqtgraph import Vector
from pyqtgraph.opengl import (
    GLLinePlotItem,
    GLMeshItem,
    GLScatterPlotItem,
    GLTextItem,
    GLViewWidget,
    MeshData,
)
from pyqtgraph.opengl.shaders import FragmentShader, ShaderProgram, VertexShader
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMatrix4x4,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QQuaternion,
    QVector3D,
    QVector4D,
    QWheelEvent,
)
from PySide6.QtWidgets import QRubberBand

from mycad.core.identity import BodyId, TopologyId
from mycad.core.signals import SignalName
from mycad.core.sketch import WorkPlaneFrame
from mycad.core.spatial_frames import RigidFrame
from mycad.core.spatial_positioning import intersect_plane
from mycad.core.spatial_references import SpatialReference
from mycad.core.viewport_protocol import (
    PlanarFaceFrame,
    Point3,
    SpatialDatumPort,
    ViewportSketchRegion,
)
from mycad.ui.body_display import visible_body_snapshot
from mycad.ui.coordinate_indicator import CoordinateIndicator
from mycad.ui.extrude_manipulator import ExtrudeManipulator
from mycad.ui.modeling_handles import DimensionHandle, plane_direction
from mycad.ui.theme import ThemeName, theme_tokens

RenderMode = Literal["shaded", "shaded-edges", "engineering-wireframe", "mesh-diagnostic"]
ViewOrientation = Literal["front", "back", "left", "right", "top", "bottom", "isometric"]
ProjectionMode = Literal["orthographic", "perspective"]


@dataclass(frozen=True)
class ViewportViewState:
    distance: float
    elevation: float
    azimuth: float
    center: tuple[float, float, float]
    orientation: ViewOrientation | None
    projection: ProjectionMode
    selection: SelectionState | None
    selection_filter: SelectionKind
    hidden_bodies: tuple[BodyId, ...]
    rotation: tuple[float, float, float, float] | None = None
    hidden_datums: tuple[SpatialReference, ...] = ()


@dataclass(frozen=True)
class DraftRelationAnnotation:
    constraint_id: str
    position: Point3
    text: str


SelectionKind = Literal["body", "face", "edge", "vertex"]

if TYPE_CHECKING:
    from mycad.core.document import Document
    from mycad.core.geometry_types import Tessellation
    from mycad.core.persistence import LoadedDocument
    from mycad.core.viewport_protocol import (
        CandidateInteractionScene,
        ViewportBoundaryEdge,
        ViewportData,
        ViewportDatum,
        ViewportPort,
        ViewportSketchData,
        ViewportSketchDimension,
        ViewportSnapAnchor,
        ViewportVertex,
    )
    from mycad.ui.part_sketch_dimensions import DraftDimensionLeader

#: Phase 2 light canvas. setBackgroundColor uses Qt colours (not GL floats).
#: Hex preserves opaque alpha; mesh/edge colours below use GL's 0..1 range.
VIEWPORT_BACKGROUND: str = "#EFF3F7"
#: Machined-part steel tone for the shaded body.
SHADED_COLOR: tuple[float, float, float, float] = (0.72, 0.75, 0.80, 1.0)
PREVIEW_COLOR: tuple[float, float, float, float] = (0.53, 0.76, 0.93, 1.0)
#: Dark blue-grey edges: readable over the body and on the bare background.
EDGE_COLOR: tuple[float, float, float, float] = (0.16, 0.19, 0.24, 1.0)
#: Current-result selection / historical preview accent.
HIGHLIGHT_COLOR: tuple[float, float, float, float] = (1.0, 0.62, 0.10, 0.45)
#: Hover candidate uses a cool blue tint, distinct from the committed amber.
PRESELECTION_COLOR: tuple[float, float, float, float] = (0.18, 0.48, 0.92, 0.42)

#: Extra room around the bounding sphere so the model never touches the border.
FIT_VIEW_MARGIN: float = 1.2

#: Geometry and command-history changes that affect the viewport scene.
#: Metadata and named groups are rendered by the right panel and must not
#: invalidate a current selection or an explicit history preview.
REFRESH_SIGNALS: tuple[SignalName, ...] = (
    "post_command",
    "geometry_rebuilt",
    "command_amended",
)
SOURCE_IDENTITY_SIGNALS: tuple[SignalName, ...] = (
    "metadata_changed",
    "named_group_added",
    "named_group_removed",
)


#: Möller–Trumbore epsilon: thickness below this counts as parallel.
RAY_EPSILON: float = 1e-9


def build_workbench_shader() -> ShaderProgram:
    """Create shader state for one GL context; compiled IDs cannot be shared."""
    return ShaderProgram(
        "mycad-workbench-lighting-v1",
        [
            VertexShader(
                """
                varying vec3 normal;
                varying vec4 vertex_color;
                void main() {
                    // Viewport mesh vertices and the key light share world coordinates.
                    normal = normalize(gl_Normal);
                    vertex_color = gl_Color;
                    gl_FrontColor = gl_Color;
                    gl_BackColor = gl_Color;
                    gl_Position = ftransform();
                }
                """
            ),
            FragmentShader(
                """
                uniform float key_light[3];
                uniform float illumination[2];
                varying vec3 normal;
                varying vec4 vertex_color;
                void main() {
                    vec3 light_direction = normalize(vec3(
                        key_light[0], key_light[1], key_light[2]
                    ));
                    float diffuse = max(dot(normalize(normal), light_direction), 0.0);
                    float light = illumination[0] + illumination[1] * diffuse;
                    vec4 color = vertex_color;
                    gl_FragColor = vec4(color.rgb * light, color.a);
                }
                """
            ),
        ],
        uniforms={"key_light": [0.35, -0.25, 0.90], "illumination": [0.45, 0.55]},
    )


def ray_triangle_hit(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float | None:
    """Signed distance ``t`` where the ray crosses triangle abc, or ``None``.

    Möller–Trumbore without backface culling: both sides of every surface
    count, because a click may land on an interior wall first.
    """
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    px = direction[1] * e2[2] - direction[2] * e2[1]
    py = direction[2] * e2[0] - direction[0] * e2[2]
    pz = direction[0] * e2[1] - direction[1] * e2[0]
    det = e1[0] * px + e1[1] * py + e1[2] * pz
    if -RAY_EPSILON < det < RAY_EPSILON:
        return None
    inv = 1.0 / det
    tx = origin[0] - a[0]
    ty = origin[1] - a[1]
    tz = origin[2] - a[2]
    u = (tx * px + ty * py + tz * pz) * inv
    if u < 0.0 or u > 1.0:
        return None
    qx = ty * e1[2] - tz * e1[1]
    qy = tz * e1[0] - tx * e1[2]
    qz = tx * e1[1] - ty * e1[0]
    v = (direction[0] * qx + direction[1] * qy + direction[2] * qz) * inv
    if v < 0.0 or u + v > 1.0:
        return None
    t = (e2[0] * qx + e2[1] * qy + e2[2] * qz) * inv
    # Only a forward crossing counts; a triangle exactly on the camera plane
    # is degenerate noise, not a pick.
    return t if t > RAY_EPSILON else None


def ray_mesh_hit(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    mesh: Tessellation,
) -> float | None:
    """Nearest forward ray×triangle distance in one snapshot mesh."""
    hit = ray_mesh_hit_triangle(origin, direction, mesh)
    return None if hit is None else hit[1]


def ray_mesh_hit_triangle(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    mesh: Tessellation,
) -> tuple[int, float] | None:
    """Index and distance of the nearest forward ray×triangle hit."""
    nearest: float | None = None
    nearest_index: int | None = None
    vertices = mesh.vertices
    for triangle_index, tri in enumerate(mesh.triangle_indices):
        t = ray_triangle_hit(
            origin,
            direction,
            vertices[tri[0]],
            vertices[tri[1]],
            vertices[tri[2]],
        )
        if t is not None and (nearest is None or t < nearest):
            nearest = t
            nearest_index = triangle_index
    if nearest is None or nearest_index is None:
        return None
    return nearest_index, nearest


def unique_edges(triangles: Sequence[tuple[int, int, int]]) -> tuple[tuple[int, int], ...]:
    """Deduplicated undirected edges of a triangle soup, index-sorted.

    A mesh of N triangles carries 3N index pairs; keeping only the distinct
    (min, max) pairs is what turns the triangle list into a wireframe that
    does not draw every shared edge twice.
    """
    pairs: set[tuple[int, int]] = set()
    for tri in triangles:
        for low, high in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            pairs.add((low, high) if low <= high else (high, low))
    return tuple(sorted(pairs))


def orientation_angles(orientation: ViewOrientation) -> tuple[float, float]:
    """Map a named standard view to GLViewWidget ``(elevation, azimuth)``."""
    angles: dict[ViewOrientation, tuple[float, float]] = {
        "front": (0.0, 270.0),
        "back": (0.0, 90.0),
        "left": (0.0, 180.0),
        "right": (0.0, 0.0),
        "top": (90.0, 0.0),
        "bottom": (-90.0, 0.0),
        "isometric": (35.264389682754654, 45.0),
    }
    try:
        return angles[orientation]
    except KeyError:
        raise ValueError(f"unsupported camera orientation: {orientation!r}") from None


def camera_basis(
    elevation_degrees: float,
    azimuth_degrees: float,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    """Return camera-to-eye, right, up, and forward unit vectors."""
    elevation = radians(elevation_degrees)
    azimuth = radians(azimuth_degrees)
    camera_direction = np.asarray(
        (
            cos(elevation) * cos(azimuth),
            cos(elevation) * sin(azimuth),
            sin(elevation),
        ),
        dtype=np.float64,
    )
    forward = -camera_direction
    # Match GLViewWidget's Euler view matrix even at the poles. Choosing a
    # fallback world-up near +/-90 degrees rotates picking relative to the
    # rendered model, and introduces a discontinuity during orbiting.
    right = np.asarray((-sin(azimuth), cos(azimuth), 0.0), dtype=np.float64)
    up = np.asarray(
        (-sin(elevation) * cos(azimuth), -sin(elevation) * sin(azimuth), cos(elevation)),
        dtype=np.float64,
    )
    return (
        (
            float(camera_direction[0]),
            float(camera_direction[1]),
            float(camera_direction[2]),
        ),
        (float(right[0]), float(right[1]), float(right[2])),
        (float(up[0]), float(up[1]), float(up[2])),
        (float(forward[0]), float(forward[1]), float(forward[2])),
    )


def view_camera_basis(matrix: QMatrix4x4) -> tuple[Point3, Point3, Point3, Point3]:
    """Read the rendered world-space camera axes, including free-view roll."""
    right = matrix.row(0)
    up = matrix.row(1)
    eye = matrix.row(2)
    return (
        (eye.x(), eye.y(), eye.z()),
        (right.x(), right.y(), right.z()),
        (up.x(), up.y(), up.z()),
        (-eye.x(), -eye.y(), -eye.z()),
    )


def point_segment_distance_2d(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Shortest logical-pixel distance from one point to a 2D segment."""
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0.0:
        return ((point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2) ** 0.5
    projection = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y) / length_squared,
        ),
    )
    closest = (start[0] + projection * delta_x, start[1] + projection * delta_y)
    return ((point[0] - closest[0]) ** 2 + (point[1] - closest[1]) ** 2) ** 0.5


def segment_intersects_rect(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> bool:
    """Whether a 2D segment intersects ``(left, top, right, bottom)``."""
    left, top, right, bottom = rect
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    lower = 0.0
    upper = 1.0
    for p_value, q_value in (
        (-delta_x, start[0] - left),
        (delta_x, right - start[0]),
        (-delta_y, start[1] - top),
        (delta_y, bottom - start[1]),
    ):
        if p_value == 0.0:
            if q_value < 0.0:
                return False
            continue
        ratio = q_value / p_value
        if p_value < 0.0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return True


def point_in_triangle_2d(
    point: tuple[float, float],
    triangle: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> bool:
    """Whether a 2D point lies inside or on a triangle."""
    first, second, third = triangle
    cross_1 = (second[0] - first[0]) * (point[1] - first[1]) - (second[1] - first[1]) * (
        point[0] - first[0]
    )
    cross_2 = (third[0] - second[0]) * (point[1] - second[1]) - (third[1] - second[1]) * (
        point[0] - second[0]
    )
    cross_3 = (first[0] - third[0]) * (point[1] - third[1]) - (first[1] - third[1]) * (
        point[0] - third[0]
    )
    has_negative = cross_1 < 0.0 or cross_2 < 0.0 or cross_3 < 0.0
    has_positive = cross_1 > 0.0 or cross_2 > 0.0 or cross_3 > 0.0
    return not (has_negative and has_positive)


@dataclass(frozen=True, slots=True)
class SelectionState:
    """Transient view selection; never part of Document or archive data."""

    geometry_revision: int
    kind: SelectionKind
    body_ids: tuple[BodyId, ...]
    topology_ids: tuple[TopologyId, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.geometry_revision, bool) or self.geometry_revision < 0:
            raise ValueError("selection revision must be a nonnegative integer")
        if len(set(self.topology_ids)) != len(self.topology_ids):
            raise ValueError("selection topology identities must be unique")
        if self.kind == "body":
            if len(set(self.body_ids)) != len(self.body_ids):
                raise ValueError("selection body identities must be unique")
            if self.topology_ids:
                raise ValueError("body selection does not carry topology identities")
        elif len(self.body_ids) != len(self.topology_ids) or not self.topology_ids:
            raise ValueError("topology selection needs one owning body per topology identity")


class _ScatterInitializer(Protocol):
    def initializeGL(self) -> None: ...  # noqa: N802


class _ContextScatterPlotItem(GLScatterPlotItem):
    """Keep the point-sprite shader local to this item's OpenGL context."""

    def initializeGL(self) -> None:  # noqa: N802
        if cast("object", self.shader) is not None:
            return
        cast("_ScatterInitializer", super()).initializeGL()
        self.shader = ShaderProgram(
            "mycad-point-sprite",
            [
                VertexShader(
                    """
                    void main() {
                        gl_FrontColor = gl_Color;
                        gl_PointSize = gl_Normal.x;
                        gl_Position = ftransform();
                    }
                    """
                )
            ],
        )


class _DepthBiasedLinePlotItem(GLLinePlotItem):
    """Keep display polylines fractionally in front of coincident mesh faces."""

    def __init__(
        self,
        positions: Sequence[tuple[float, float, float]],
        *,
        color: tuple[float, float, float, float],
    ) -> None:
        self._base_positions = np.asarray(positions, dtype=np.float32)
        super().__init__(
            pos=self._base_positions,
            mode="lines",
            color=color,
            width=1.0,
            glOptions="opaque",
        )

    def set_positions(self, positions: Sequence[tuple[float, float, float]]) -> None:
        """Replace exact world-space points, retaining a copy for drawing."""
        self._base_positions = np.asarray(positions, dtype=np.float32)
        self.setData(pos=self._base_positions)

    def paint(self) -> None:
        """Apply a small camera-facing draw offset to avoid depth-buffer flicker."""
        view = self.view()
        if self._base_positions.size and view is not None:
            camera_direction = np.asarray(view_camera_basis(view.viewMatrix())[0], dtype=np.float32)
            span = float(np.ptp(self._base_positions, axis=0).max())
            offset = max(0.01, span * 1e-4)
            self.pos = self._base_positions + camera_direction * offset
        super().paint()


class _SketchOverlayLinePlotItem(_DepthBiasedLinePlotItem):
    """Draw the active sketch after the model, including inside solid geometry."""

    def __init__(
        self,
        positions: Sequence[tuple[float, float, float]],
        *,
        color: tuple[float, float, float, float],
    ) -> None:
        super().__init__(positions, color=color)
        # OpenGL GL_DEPTH_TEST and GL_BLEND: show the exact sketch color over the model.
        self.setGLOptions({0x0B71: False, 0x0BE2: False})
        self.setDepthValue(10)


class GLViewport(GLViewWidget):
    """Central viewport with explicit BREP-boundary and diagnostic modes.

    Mouse rotate/pan/wheel-zoom are ``GLViewWidget``'s built-ins and are kept
    untouched; ``fit_view()`` is the only camera this class drives. No
    antialiasing or material work (UI 初稿 §9 asks for an industrial
    grey-blue base tone only).

    A click becomes a camera ray (pinhole model, fov from the widget) and is
    intersected with the current snapshot only. The selected current result
    is not attributed to a command because the protocol has no entity-source
    mapping. Feature-tree clicks enter explicit history preview by replacing
    the displayed state with that feature's post-command snapshot.
    """

    # Click on the current model result; False means selection was cleared.
    current_entity_picked = Signal(bool)
    datum_selection_changed = Signal(object)
    # Full transient identity state, shared with status and structure panel.
    selection_changed = Signal(object)
    current_snapshot_changed = Signal(object)
    camera_changed = Signal()
    body_display_changed = Signal()
    # Right-click and Escape route to the active contextual modeling tool.
    context_menu_requested = Signal(QPoint)
    fillet_commit_requested = Signal()
    modeling_commit_requested = Signal()
    radius_edit_requested = Signal(str)
    escape_pressed = Signal()
    # Point placement for base-plane primitives (box and parametric extrusion).
    workplane_point_picked = Signal(object, QPoint)
    workplane_point_rejected = Signal()
    # Whether a tree-driven historical state preview is active.
    history_preview_changed = Signal(bool)
    # Core events may be produced by the serialized CAD worker. Delivery is
    # queued back to this widget's owning thread before any timer is touched.
    _core_event_queued = Signal(int, str, object)

    def __init__(self, *, viewport_port: ViewportPort) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.setBackgroundColor(VIEWPORT_BACKGROUND)
        self.setMinimumSize(160, 120)
        self._projection_mode: ProjectionMode = "orthographic"
        self._orientation: ViewOrientation | None = None
        self._selection_filter: SelectionKind = "body"
        self._hidden_body_ids: set[BodyId] = set()
        self._visibility_source: ViewportData | None = None
        self._visible_snapshot_cache: ViewportData | None = None
        self._modeling_context_active = False
        self._modeling_interaction_locked = False
        self._fillet_interaction_active = False
        self._fillet_radius_input_valid = True
        self._placement_context_active = False
        self._face_origin_snap_enabled = False
        self._selection: SelectionState | None = None
        self._preselection: SelectionState | None = None
        self._rubber_start: tuple[float, float] | None = None
        self._rubber_crossing = False
        self._coordinate_axes_visible = True
        self._xy_grid_visible = False
        self._workplane_grid: GLScatterPlotItem | None = None
        self._position_marker: GLScatterPlotItem | None = None
        self._origin_hotspot: Point3 | None = None
        self._position_projection_line: GLLinePlotItem | None = None
        self._position_points: tuple[Point3, ...] = ()
        self.coordinate_indicator = CoordinateIndicator(
            self, self.viewMatrix, lambda: self.project_world_point((0.0, 0.0, 0.0))
        )
        self._xy_grid = _ContextScatterPlotItem(
            pos=np.array(
                [(x, y, 0.0) for x in range(-100, 101, 10) for y in range(-100, 101, 10)],
                dtype=np.float32,
            ),
            color=(0.25, 0.35, 0.45, 0.55),
            size=2.0,
            pxMode=True,
            glOptions="translucent",
        )
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._port = viewport_port
        self._workbench_shader = build_workbench_shader()
        self._edge_color = EDGE_COLOR
        self._mesh_item: GLMeshItem | None = None
        self._edge_item: GLLinePlotItem | None = None
        self._mesh_edge_item: GLLinePlotItem | None = None
        self._sketch_items: list[_DepthBiasedLinePlotItem] = []
        self._sketch_point_items: list[GLScatterPlotItem] = []
        self._draft_sketch_items: list[_DepthBiasedLinePlotItem] = []
        self._draft_points: tuple[tuple[str, Point3], ...] = ()
        self._draft_point_item: GLScatterPlotItem | None = None
        self._draft_controls: tuple[Point3, ...] = ()
        self._draft_control_item: GLScatterPlotItem | None = None
        self._draft_regions: tuple[ViewportSketchRegion, ...] = ()
        self._draft_region_items: list[GLMeshItem] = []
        self._draft_relation_items: list[GLTextItem] = []
        self._draft_relation_texts: tuple[str, ...] = ()
        self._draft_relations: tuple[DraftRelationAnnotation, ...] = ()
        self._draft_dimension_items: list[GLTextItem] = []
        self._draft_dimensions: tuple[ViewportSketchDimension, ...] = ()
        self._draft_dimension_leader_items: list[_SketchOverlayLinePlotItem] = []
        self._active_draft_sketch_id: str | None = None
        self._sketch_dimension_items: list[GLTextItem] = []
        self._sketch_dimension_label_count = 0
        self._mesh: Tessellation | None = None
        self._mesh_data: MeshData | None = None
        self._render_mode: RenderMode = "shaded-edges"
        self._rebuilds = 0
        self._snapshot_count = 0
        self._snapshots: tuple[ViewportData, ...] = ()
        self._history_state_ids: tuple[str, ...] = ()
        self._preview_snapshot: ViewportData | None = None
        self._candidate_snapshot: ViewportData | None = None
        self._interaction_scene: CandidateInteractionScene | None = None
        self._interaction_guard: Callable[[], bool] | None = None
        self._datum_items: list[GLLinePlotItem | GLTextItem] = []
        self._hidden_datums: set[SpatialReference] = set()
        self._datum_pick_filter: frozenset[SpatialReference] | None = None
        self._selected_datum: SpatialReference | None = None
        self._preselected_datum: SpatialReference | None = None
        self._datum_cycle: tuple[SpatialReference, ...] = ()
        self._datum_cycle_position: tuple[float, float] | None = None
        self._datum_cycle_index = 0
        self._candidate_sketches: tuple[ViewportSketchData, ...] | None = None
        self._candidate_camera_state: tuple[float, tuple[float, float, float]] | None = None
        self._candidate_preserve_view = False
        self._refresh_pending = False
        self._refresh_after_busy = False
        self._execution_busy = False
        self._disposed = False
        self._binding_id = 0
        # Parented so a pending rebuild dies with the widget: an orphaned
        # singleShot outlives the C++ object and would call refresh() on
        # deleted shiboken memory.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._run_scheduled_refresh)
        self._core_event_queued.connect(self._receive_core_event)
        # The signal bus holds subscribers weakly (core/signals.py), so the
        # per-signal adapters need strong owners until the next bind/close.
        self._adapters: list[Callable[[Mapping[str, object]], None]] = []
        # Snapshot state IDs map to their producing command ordinal only for
        # explicit history preview. Current entity selection never uses it.
        self._document: Document | None = None
        self._source_revision: int | None = None
        self._ordinal_of_state: dict[str, int] = {}
        self._current_state_id: str | None = None
        self._preview_state_id: str | None = None
        self._current_entity_selected = False
        self._selection_item: GLMeshItem | None = None
        self._selection_line_item: GLLinePlotItem | None = None
        self._pressed_pos: tuple[float, float] | None = None
        self._right_press_pos: tuple[float, float] | None = None
        self._right_press_started = 0.0
        self._modeling_navigation_pos: tuple[float, float] | None = None
        self._last_face_hit: tuple[TopologyId, Point3] | None = None
        self._last_face_screen: tuple[float, float] | None = None
        self._last_face_snap_bypassed = False
        self._last_face_origin_snapped = False
        self.extrude_manipulator = ExtrudeManipulator(
            self, self.project_world_point, self.camera_ray
        )

    # ------------------------------------------------------------------
    # Document binding and refresh coalescing
    # ------------------------------------------------------------------

    def set_viewport_port(self, port: ViewportPort) -> None:
        self._port = port

    def capture_view(self) -> ViewportViewState:
        distance, center = self.camera_state()
        rotation: QQuaternion = self.opts["rotation"]
        return ViewportViewState(
            distance,
            float(self.opts["elevation"]),
            float(self.opts["azimuth"]),
            center,
            self._orientation,
            self._projection_mode,
            self.selection(),
            self._selection_filter,
            self.hidden_body_ids(),
            (rotation.scalar(), rotation.x(), rotation.y(), rotation.z())
            if self.opts["rotationMethod"] == "quaternion"
            else None,
            tuple(sorted(self._hidden_datums, key=lambda item: item.source_instance_id or "")),
        )

    def restore_view(self, state: ViewportViewState) -> None:
        self._orientation = state.orientation
        self.set_projection_mode(state.projection)
        self.setCameraPosition(
            pos=QVector3D(*state.center),
            distance=state.distance,
            elevation=state.elevation,
            azimuth=state.azimuth,
        )
        if state.rotation is not None:
            self.setCameraPosition(rotation=QQuaternion(*state.rotation))
        self._hidden_datums = set(state.hidden_datums)
        self.set_selection_filter(state.selection_filter)
        for identity in state.hidden_bodies:
            self.set_body_visible(identity, False)
        self._render_active_state()
        snapshot = self._current_snapshot()
        if (
            snapshot is not None
            and state.selection is not None
            and state.selection.geometry_revision == snapshot.geometry_revision
        ):
            self._apply_selection_targets((state.selection,), toggle=False)

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Subscribe the refresh union to ``loaded`` and render it once."""
        self.extrude_manipulator.clear()
        self._last_face_hit = None
        self._last_face_screen = None
        self._last_face_origin_snapped = False
        was_selected = self._selection is not None or self._current_entity_selected
        was_previewing = self._preview_state_id is not None
        self._document = loaded.document
        self._hidden_body_ids.clear()
        self._hidden_datums.clear()
        self._selected_datum = None
        self._preselected_datum = None
        self._visibility_source = None
        self._visible_snapshot_cache = None
        self._binding_id += 1
        self._preview_state_id = None
        self._preview_snapshot = None
        self._candidate_snapshot = None
        self._interaction_scene = None
        self._interaction_guard = None
        self._candidate_camera_state = None
        self._candidate_preserve_view = False
        self._current_entity_selected = False
        self._selection = None
        self._preselection = None
        self._adapters.clear()
        events = loaded.document.events
        for name in (*REFRESH_SIGNALS, *SOURCE_IDENTITY_SIGNALS):
            adapter = partial(self._queue_refresh_signal, self._binding_id, name)
            self._adapters.append(adapter)
            events.subscribe(name, adapter)
        self.refresh()
        if was_selected:
            self.current_entity_picked.emit(False)
            self.selection_changed.emit(None)
        if was_previewing:
            self.history_preview_changed.emit(False)

    def _queue_refresh_signal(
        self, binding_id: int, name: str, payload: Mapping[str, object]
    ) -> None:
        """Relay worker-thread notifications without touching widget state."""
        self._core_event_queued.emit(binding_id, name, dict(payload))

    def _receive_core_event(
        self, binding_id: int, name: str, payload: Mapping[str, object]
    ) -> None:
        """Handle only the currently bound document on the UI thread."""
        if self._disposed or binding_id != self._binding_id:
            return
        if (
            name in SOURCE_IDENTITY_SIGNALS
            and not self._refresh_pending
            and not self._execution_busy
        ):
            self._source_revision = self._document.revision if self._document is not None else None
            return
        self._schedule_refresh()

    def set_execution_busy(self, busy: bool) -> None:
        """Defer viewport reads until the serialized kernel operation ends."""
        if busy == self._execution_busy:
            return
        self._execution_busy = busy
        self.body_display_changed.emit()
        if busy:
            if self._refresh_pending:
                self._refresh_after_busy = True
            self._refresh_timer.stop()
            self._refresh_pending = False
        elif self._refresh_after_busy:
            self._refresh_after_busy = False
            self._schedule_refresh()

    def _on_refresh_signal(self, name: str, payload: Mapping[str, object]) -> None:
        """Signal adapter retained for direct, same-thread internal callers."""
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        """Collapse every signal of one event-loop turn into one rebuild."""
        if self._execution_busy:
            self._refresh_after_busy = True
            return
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._refresh_timer.start()

    def _run_scheduled_refresh(self) -> None:
        self._refresh_pending = False
        if self._disposed:
            return
        if self._execution_busy:
            self._refresh_after_busy = True
            return
        try:
            self.refresh()
        except RuntimeError:
            # shiboken: a wrapper can outlive its C++ deletion when teardown
            # bypasses closeEvent; a post-mortem rebuild stays inert instead
            # of poisoning the next test's event loop.
            return

    def dispose(self) -> None:
        """Drop the subscriptions and stop pending rebuilds on window close."""
        self.extrude_manipulator.clear()
        self._disposed = True
        self._hidden_body_ids.clear()
        self._visibility_source = None
        self._visible_snapshot_cache = None
        self._binding_id += 1
        self._refresh_timer.stop()
        self._refresh_pending = False
        self._refresh_after_busy = False
        self._adapters.clear()
        self._ordinal_of_state = {}
        self._snapshots = ()
        self._history_state_ids = ()
        self._preview_snapshot = None
        self._candidate_snapshot = None
        self._candidate_camera_state = None
        self._preview_state_id = None
        self._current_state_id = None
        self._current_entity_selected = False
        self._document = None
        self._source_revision = None
        self._interaction_scene = None
        self._interaction_guard = None
        self._mesh = None
        self.set_workplane_grid(None, 1.0)
        self.set_position_markers(None)
        self._clear_items()
        self._clear_sketch_items()
        self._clear_datum_items()

    def refresh(self) -> None:
        """Re-read the current mesh and history IDs, then rebuild the scene."""
        if self._disposed:
            return
        if self._execution_busy:
            self._refresh_after_busy = True
            return
        # A direct refresh (for example, the completion of an explicit worker
        # rebuild) satisfies any coalesced refresh already waiting on the timer.
        self._refresh_timer.stop()
        self._refresh_pending = False
        self._refresh_after_busy = False
        self._rebuilds += 1
        revision = self._document.revision if self._document is not None else None
        snapshots = self._port.viewport_data()
        state_ids = self._port.viewport_state_ids()
        if self._document is not None and self._document.revision != revision:
            self._schedule_refresh()
            return
        self._source_revision = revision
        had_selection = self._selection is not None or self._current_entity_selected
        previous_preview = self._preview_state_id
        self._snapshots = snapshots
        self._hidden_body_ids.intersection_update(
            snapshots[-1].triangle_body_ids if snapshots else ()
        )
        self._visible_snapshot_cache = None
        self._history_state_ids = state_ids
        self._snapshot_count = len(state_ids)
        self._rebuild_state_map(state_ids)
        self._current_state_id = snapshots[-1].state_id if snapshots else None
        self._current_entity_selected = False
        self._selection = None
        self._preselection = None
        # A refreshed model invalidates a history inspection context. The
        # user can explicitly choose a row again against the new snapshots.
        self._preview_state_id = None
        self._preview_snapshot = None
        self._candidate_snapshot = None
        self._candidate_camera_state = None
        if self._interaction_scene is not None and not self._interaction_scene_current():
            self._interaction_scene = None
            self._interaction_guard = None
        self._render_active_state()
        self.current_snapshot_changed.emit(snapshots[-1] if snapshots else None)
        if had_selection:
            self.current_entity_picked.emit(False)
            self.selection_changed.emit(None)
        if previous_preview is not None:
            self.history_preview_changed.emit(False)

    def rebuild_count(self) -> int:
        """How many rebuilds ran — the observable that proves coalescing."""
        return self._rebuilds

    def snapshot_count(self) -> int:
        """How many kernel snapshots the last refresh saw (todo 10 hooks)."""
        return self._snapshot_count

    def sketch_item_count(self) -> int:
        """Number of currently rendered non-pickable sketch curves."""
        return len(self._sketch_items)

    def set_draft_sketch_control_points(self, points: tuple[Point3, ...]) -> None:
        """Display editable control points for the selected spline."""
        if not points and self._draft_control_item is not None:
            self.removeItem(self._draft_control_item)
            self._draft_control_item = None
        self._draft_controls = points
        if points:
            positions = np.asarray(points, dtype=np.float32)
            if self._draft_control_item is None:
                self._draft_control_item = _ContextScatterPlotItem(
                    pos=positions, color=(1.0, 0.55, 0.05, 1.0), size=9, pxMode=True
                )
                self.addItem(self._draft_control_item)
            else:
                self._draft_control_item.setData(pos=positions)
        self.update()

    def draft_sketch_control_points(self) -> tuple[Point3, ...]:
        return self._draft_controls

    def set_draft_sketch_points(
        self, points: tuple[tuple[str, Point3], ...], *, selected_id: str | None = None
    ) -> None:
        """Display transient sketch points with a fixed logical-pixel size."""
        if not points and self._draft_point_item is not None:
            self.removeItem(self._draft_point_item)
            self._draft_point_item = None
        self._draft_points = points
        if points:
            colors = np.asarray(
                [
                    (1.0, 0.55, 0.05, 1.0) if identity == selected_id else (0.1, 0.35, 0.75, 1.0)
                    for identity, _ in points
                ],
                dtype=np.float32,
            )
            positions = np.asarray([point for _, point in points], dtype=np.float32)
            if self._draft_point_item is None:
                self._draft_point_item = _ContextScatterPlotItem(
                    pos=positions, color=colors, size=9, pxMode=True
                )
                self.addItem(self._draft_point_item)
            else:
                self._draft_point_item.setData(pos=positions, color=colors)
        self.update()

    def draft_sketch_point_at(self, x: float, y: float) -> str | None:
        """Pick a visible draft point using logical screen pixels."""
        candidates: list[tuple[float, str]] = []
        for identity, point in self._draft_points:
            screen = self.project_world_point(point)
            if screen is not None:
                distance = dist((x, y), screen)
                if distance <= 9:
                    candidates.append((distance, identity))
        return min(candidates)[1] if candidates else None

    def set_draft_sketch_regions(
        self,
        regions: tuple[ViewportSketchRegion, ...],
        *,
        selected: tuple[str, ...] | None = None,
        hovered: tuple[str, ...] | None = None,
    ) -> None:
        """Display the exact candidate meshes used for region picking."""
        for item in self._draft_region_items:
            self.removeItem(item)
        self._draft_region_items.clear()
        self._draft_regions = regions
        for region in regions:
            mesh = MeshData(
                vertexes=np.asarray(region.mesh.vertices, dtype=np.float32),
                faces=np.asarray(region.mesh.triangle_indices, dtype=np.int32),
            )
            color = (
                (1.0, 0.55, 0.05, 0.5)
                if region.boundary_entity_ids == selected
                else (0.2, 0.65, 0.95, 0.4)
                if region.boundary_entity_ids == hovered
                else (0.25, 0.55, 0.85, 0.2)
            )
            item = GLMeshItem(meshdata=mesh, color=color, glOptions="translucent", smooth=False)
            self._draft_region_items.append(item)
            self.addItem(item)
        self.update()

    def draft_sketch_region_at(self, x: float, y: float) -> tuple[str, ...] | None:
        """Return the closest visible draft region under a logical viewport pixel."""
        ray = self.camera_ray(x, y)
        if ray is None:
            return None
        nearest: tuple[float, tuple[str, ...]] | None = None
        for region in self._draft_regions:
            hit = ray_mesh_hit_triangle(ray[0], ray[1], region.mesh)
            if hit is not None and (nearest is None or hit[1] < nearest[0]):
                nearest = (hit[1], region.boundary_entity_ids)
        if nearest is None:
            return None
        snapshot = self._current_snapshot()
        if snapshot is not None:
            obstruction = ray_mesh_hit_triangle(ray[0], ray[1], snapshot.mesh)
            if obstruction is not None and obstruction[1] < nearest[0] - 1e-5:
                return None
        return nearest[1]

    def set_draft_sketch_curves(
        self,
        curves: Sequence[tuple[Point3, ...]],
        *,
        selected_index: int | None = None,
        construction_indices: frozenset[int] = frozenset(),
    ) -> None:
        """Display transient part-sketch geometry without altering the model scene."""
        for item in self._draft_sketch_items:
            self.removeItem(item)
        self._draft_sketch_items.clear()

        def interpolate(start: Point3, end: Point3, factor: float) -> Point3:
            return (
                start[0] + (end[0] - start[0]) * factor,
                start[1] + (end[1] - start[1]) * factor,
                start[2] + (end[2] - start[2]) * factor,
            )

        for index, curve in enumerate(curves):
            segments = tuple(zip(curve, curve[1:], strict=False))
            if index in construction_indices and len(segments) > 10:
                segments = segments[::2]
            elif index in construction_indices:
                segments = tuple(
                    (
                        interpolate(start, end, step / 12),
                        interpolate(start, end, (step + 1) / 12),
                    )
                    for start, end in segments
                    for step in range(0, 12, 2)
                )
            positions = tuple(point for start, end in segments for point in (start, end))
            if positions:
                color = (
                    (1.0, 0.55, 0.05, 1.0)
                    if index == selected_index
                    else (0.45, 0.52, 0.58, 1.0)
                    if index in construction_indices
                    else (0.1, 0.35, 0.75, 1.0)
                )
                item = _SketchOverlayLinePlotItem(positions, color=color)
                self._draft_sketch_items.append(item)
                self.addItem(item)
        self.update()

    def draft_sketch_curve_count(self) -> int:
        """Return the number of transient sketch curves currently displayed."""
        return len(self._draft_sketch_items)

    def set_draft_relation_labels(self, labels: tuple[tuple[Point3, str], ...]) -> None:
        """Display transient relation symbols for the active sketch draft."""
        self._draft_relations = ()
        for item in self._draft_relation_items:
            self.removeItem(item)
        self._draft_relation_items.clear()
        self._draft_relation_texts = tuple(text for _, text in labels)
        for point, text in labels:
            item = GLTextItem(pos=point, text=text, color=(30, 116, 65, 255))
            self._draft_relation_items.append(item)
            self.addItem(item)
        self.update()

    def draft_relation_labels(self) -> tuple[str, ...]:
        """Return relation symbols currently displayed for the draft."""
        return self._draft_relation_texts

    def set_draft_relation_annotations(
        self, annotations: tuple[DraftRelationAnnotation, ...]
    ) -> None:
        """Display relation symbols with the corresponding stable constraint IDs."""
        self.set_draft_relation_labels(tuple((item.position, item.text) for item in annotations))
        self._draft_relations = annotations

    def draft_relation_annotations(self) -> tuple[DraftRelationAnnotation, ...]:
        return self._draft_relations

    def draft_relations_at(self, x: float, y: float) -> tuple[str, ...]:
        candidates: list[tuple[float, str]] = []
        for annotation in self._draft_relations:
            point = self.project_world_point(annotation.position)
            if point is not None and abs(point[0] - x) <= 12 and abs(point[1] - y) <= 12:
                candidates.append(
                    ((point[0] - x) ** 2 + (point[1] - y) ** 2, annotation.constraint_id)
                )
        return tuple(identity for _, identity in sorted(candidates))

    def set_draft_sketch_dimensions(self, dimensions: tuple[ViewportSketchDimension, ...]) -> None:
        """Display identifiable dimensions belonging to the active sketch draft."""
        for item in self._draft_dimension_items:
            self.removeItem(item)
        self._draft_dimension_items.clear()
        self._draft_dimensions = dimensions
        if not dimensions:
            self.set_draft_dimension_leaders(())
        for dimension in dimensions:
            font = QFont("Sans Serif")
            font.setPointSizeF(max(8.0, min(24.0, 10.0 * dimension.scale**0.5)))
            item = GLTextItem(
                pos=dimension.position,
                text=dimension.text,
                color=(*dimension.color_rgb, 255),
                font=font,
                glOptions="translucent",
            )
            self._draft_dimension_items.append(item)
            self.addItem(item)
        self.update()

    def draft_sketch_dimensions(self) -> tuple[ViewportSketchDimension, ...]:
        """Return currently displayed draft dimensions with stable identities."""
        return self._draft_dimensions

    def set_draft_dimension_leaders(self, leaders: tuple[DraftDimensionLeader, ...]) -> None:
        """Display transient lines connecting dimension labels to geometry."""
        for item in self._draft_dimension_leader_items:
            self.removeItem(item)
        self._draft_dimension_leader_items.clear()
        for leader in leaders:
            positions = tuple(point for segment in leader.segments for point in segment)
            red, green, blue = leader.color_rgb
            item = _SketchOverlayLinePlotItem(
                positions, color=(red / 255.0, green / 255.0, blue / 255.0, 1.0)
            )
            self._draft_dimension_leader_items.append(item)
            self.addItem(item)
        self.update()

    def draft_dimensions_at(self, x: float, y: float) -> tuple[str, ...]:
        """Find visible draft dimension labels at a screen position."""
        candidates: list[tuple[float, str]] = []
        for dimension in self._draft_dimensions:
            point = self.project_world_point(dimension.position)
            if point is None:
                continue
            font = QFont("Sans Serif")
            font.setPointSizeF(max(8.0, min(24.0, 10.0 * dimension.scale**0.5)))
            metrics = QFontMetrics(font)
            if (
                point[0] - 5 <= x <= point[0] + metrics.horizontalAdvance(dimension.text) + 5
                and point[1] - metrics.height() - 5 <= y <= point[1] + 5
            ):
                candidates.append(
                    ((x - point[0]) ** 2 + (y - point[1]) ** 2, dimension.constraint_id)
                )
        return tuple(identity for _, identity in sorted(candidates))

    def set_active_draft_sketch(self, sketch_id: str | None) -> None:
        """Suppress committed labels for the sketch currently being edited."""
        if self._active_draft_sketch_id != sketch_id:
            self._active_draft_sketch_id = sketch_id
            self._render_active_state()

    def sketch_dimension_label_count(self) -> int:
        """Number of visible dimension labels overlaid with sketch geometry."""
        return self._sketch_dimension_label_count

    def snapshots(self) -> tuple[ViewportData, ...]:
        """The current mesh loaded by the last refresh, if any."""
        return self._snapshots

    def history_state_ids(self) -> tuple[str, ...]:
        """History identifiers available for explicit on-demand preview."""
        return self._history_state_ids

    # ------------------------------------------------------------------
    # Current-result selection and explicit history preview
    # ------------------------------------------------------------------

    def _rebuild_state_map(self, state_ids: Sequence[str]) -> None:
        """History ID order equals Document.commands order — zip into a map.

        A size mismatch (document replay and viewport read diverge) drops
        the map instead of guessing: history preview degrades to nothing, no
        wrong ordinal is ever produced.
        """
        self._ordinal_of_state = {}
        if self._document is None:
            return
        commands = tuple(self._document.commands)
        if len(commands) != len(state_ids):
            return
        self._ordinal_of_state = {
            state_id: int(command.ordinal)
            for state_id, command in zip(state_ids, commands, strict=True)
        }

    def camera_ray(
        self, x: float, y: float
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        """Return a normalized camera ray through a logical widget pixel."""
        distance = float(self.opts["distance"])
        center: QVector3D = self.opts["center"]
        width, height = float(self.width()), float(self.height())
        if width <= 0.0 or height <= 0.0 or distance <= 0.0:
            return None
        camera_direction, right, up, forward = view_camera_basis(self.viewMatrix())
        camera_vector = np.asarray(camera_direction, dtype=np.float64)
        right_vector = np.asarray(right, dtype=np.float64)
        up_vector = np.asarray(up, dtype=np.float64)
        forward_vector = np.asarray(forward, dtype=np.float64)
        half_width = tan(radians(float(self.opts["fov"])) / 2.0) * distance
        half_height = half_width * (height / width)
        px = ((2.0 * x / width) - 1.0) * half_width
        py = (1.0 - (2.0 * y / height)) * half_height
        center_vector = np.asarray((center.x(), center.y(), center.z()), dtype=np.float64)
        camera_point = center_vector + camera_vector * distance
        if self._projection_mode == "orthographic":
            origin = camera_point + right_vector * px + up_vector * py
            direction = forward_vector
        else:
            origin = camera_point
            direction = forward_vector * distance + right_vector * px + up_vector * py
        direction_norm = float(np.linalg.norm(direction))
        if direction_norm <= 0.0:
            return None
        unit = direction / direction_norm
        return (
            (float(origin[0]), float(origin[1]), float(origin[2])),
            (float(unit[0]), float(unit[1]), float(unit[2])),
        )

    def xy_workplane_point_at(self, x: float, y: float) -> tuple[float, float, float] | None:
        """Intersect a logical viewport point with the global XY work plane."""
        ray = self.camera_ray(x, y)
        if ray is None:
            return None
        origin, direction = ray
        if abs(direction[2]) <= 1e-9:
            return None
        distance = -origin[2] / direction[2]
        if distance < 0.0:
            return None
        return (
            origin[0] + direction[0] * distance,
            origin[1] + direction[1] * distance,
            0.0,
        )

    def world_origin_hit(self, x: float, y: float) -> bool:
        """Test the visible world origin in logical pixels."""
        origin = self.project_world_point((0.0, 0.0, 0.0))
        return self._coordinate_axes_visible and origin is not None and dist((x, y), origin) <= 12

    def placement_point_at(
        self, x: float, y: float, *, bypass_snap: bool = False
    ) -> tuple[float, float, float] | None:
        """Locate on XY, snapping the pointer to the visible world origin."""
        point = self.xy_workplane_point_at(x, y)
        if point is not None and not bypass_snap and self.world_origin_hit(x, y):
            return (0.0, 0.0, 0.0)
        return point

    def project_world_point(self, point: tuple[float, float, float]) -> tuple[float, float] | None:
        """Project one world-space point into logical widget coordinates."""
        width, height = float(self.width()), float(self.height())
        distance = float(self.opts["distance"])
        if width <= 0.0 or height <= 0.0 or distance <= 0.0:
            return None
        center: QVector3D = self.opts["center"]
        _, right, up, forward = view_camera_basis(self.viewMatrix())
        relative = np.asarray(
            (point[0] - center.x(), point[1] - center.y(), point[2] - center.z()),
            dtype=np.float64,
        )
        right_component = float(np.dot(relative, right))
        up_component = float(np.dot(relative, up))
        fov = radians(float(self.opts["fov"]))
        if self._projection_mode == "orthographic":
            half_width = distance * tan(fov / 2.0)
            half_height = half_width * (height / width)
            return (
                width / 2.0 + right_component * width / (2.0 * half_width),
                height / 2.0 - up_component * height / (2.0 * half_height),
            )
        camera_depth = distance + float(np.dot(relative, forward))
        if camera_depth <= 0.0:
            return None
        half_horizontal_tangent = tan(fov / 2.0)
        half_vertical_tangent = half_horizontal_tangent * height / width
        return (
            width / 2.0 + right_component * width / (2.0 * camera_depth * half_horizontal_tangent),
            height / 2.0 - up_component * height / (2.0 * camera_depth * half_vertical_tangent),
        )

    def selection_target_at(
        self,
        x: float,
        y: float,
        kind: SelectionKind,
    ) -> SelectionState | None:
        """Resolve one body, face, edge or vertex at a logical pointer point."""
        scene = self._interaction_scene
        if scene is not None:
            if not self._interaction_scene_current():
                return None
            snapshot = scene.viewport
        else:
            if not self._source_scene_current():
                return None
            snapshot = self._current_snapshot()
        if (
            snapshot is None
            or self._preview_state_id is not None
            or (self._candidate_snapshot is not None and scene is None)
        ):
            return None
        if kind in ("body", "face"):
            ray = self.camera_ray(x, y)
            if ray is None:
                return None
            hit = ray_mesh_hit_triangle(ray[0], ray[1], snapshot.mesh)
            if hit is None:
                return None
            triangle_index = hit[0]
            body_id = snapshot.triangle_body_ids[triangle_index]
            if kind == "body":
                return SelectionState(snapshot.geometry_revision, "body", (body_id,))
            face_id = snapshot.triangle_face_ids[triangle_index]
            return SelectionState(snapshot.geometry_revision, "face", (body_id,), (face_id,))

        if kind == "edge":
            nearest: tuple[float, ViewportBoundaryEdge] | None = None
            for edge in snapshot.boundary_edges:
                projected = tuple(self.project_world_point(point) for point in edge.points)
                for start, end in zip(projected, projected[1:], strict=False):
                    if start is None or end is None:
                        continue
                    gap = point_segment_distance_2d((x, y), start, end)
                    if nearest is None or gap < nearest[0]:
                        nearest = (gap, edge)
            if nearest is not None and nearest[0] <= 6.0:
                edge = nearest[1]
                return SelectionState(
                    snapshot.geometry_revision,
                    "edge",
                    (edge.body_id,),
                    (edge.topology_id,),
                )
            return None

        nearest_vertex: tuple[float, ViewportVertex] | None = None
        for vertex in snapshot.vertices:
            projected = self.project_world_point(vertex.point)
            if projected is None:
                continue
            gap = ((projected[0] - x) ** 2 + (projected[1] - y) ** 2) ** 0.5
            if nearest_vertex is None or gap < nearest_vertex[0]:
                nearest_vertex = (gap, vertex)
        if nearest_vertex is not None and nearest_vertex[0] <= 6.0:
            vertex = nearest_vertex[1]
            return SelectionState(
                snapshot.geometry_revision,
                "vertex",
                (vertex.body_id,),
                (vertex.topology_id,),
            )
        return None

    def pick_current_entity_at_ray(
        self, origin: tuple[float, float, float], direction: tuple[float, float, float]
    ) -> bool:
        """Whether the ray hits the current whole-model result."""
        if (
            self._preview_state_id is not None
            or self._candidate_snapshot is not None
            or self._interaction_scene is not None
            or not self._source_scene_current()
        ):
            return False
        snapshot = self._current_snapshot()
        if snapshot is None or not snapshot.mesh.triangle_indices:
            return False
        hit = ray_mesh_hit(origin, direction, snapshot.mesh)
        return hit is not None

    def pick_at(
        self, x: float, y: float, *, toggle: bool = False, bypass_origin_snap: bool = False
    ) -> bool:
        """Select the filtered current topology under the pointer."""
        target = self.selection_target_at(x, y, self._selection_filter)
        if target is None:
            if not toggle and not self._modeling_context_active:
                self.clear_selection()
            return self.selection() is not None
        if target.kind == "face":
            snapshot = self._interaction_snapshot()
            ray = self.camera_ray(x, y)
            if snapshot is not None and ray is not None:
                hit = ray_mesh_hit_triangle(ray[0], ray[1], snapshot.mesh)
                if hit is not None:
                    origin, direction = ray
                    point: Point3 = (
                        origin[0] + direction[0] * hit[1],
                        origin[1] + direction[1] * hit[1],
                        origin[2] + direction[2] * hit[1],
                    )
                    self._last_face_hit = (target.topology_ids[0], point)
                    self._last_face_screen = (x, y)
                    self._last_face_snap_bypassed = bypass_origin_snap
        self._selection = self._combine_selection_target(self._selection, target, toggle)
        self._current_entity_selected = self._selection is not None
        self._preselection = None
        self._sync_selection()
        self.current_entity_picked.emit(self._selection is not None)
        self.selection_changed.emit(self._selection)
        return self._selection is not None

    @staticmethod
    def _combine_selection_target(
        current: SelectionState | None,
        target: SelectionState,
        toggle: bool,
    ) -> SelectionState | None:
        """Replace the selection or Ctrl-toggle one body/topology identity."""
        if (
            not toggle
            or current is None
            or current.kind != target.kind
            or current.geometry_revision != target.geometry_revision
        ):
            return target
        if target.kind == "body":
            body_ids = list(current.body_ids)
            body_id = target.body_ids[0]
            if body_id in body_ids:
                body_ids.remove(body_id)
            else:
                body_ids.append(body_id)
            return (
                None
                if not body_ids
                else SelectionState(target.geometry_revision, "body", tuple(body_ids))
            )
        pairs = list(zip(current.body_ids, current.topology_ids, strict=True))
        pair = (target.body_ids[0], target.topology_ids[0])
        if pair in pairs:
            pairs.remove(pair)
        else:
            pairs.append(pair)
        if not pairs:
            return None
        return SelectionState(
            target.geometry_revision,
            target.kind,
            tuple(body_id for body_id, _topology_id in pairs),
            tuple(topology_id for _body_id, topology_id in pairs),
        )

    def targets_in_screen_rect(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        crossing: bool,
    ) -> tuple[SelectionState, ...]:
        """Return filtered topology contained by or crossed by a screen box."""
        snapshot = self._current_snapshot() if self._source_scene_current() else None
        if (
            snapshot is None
            or self._preview_state_id is not None
            or self._candidate_snapshot is not None
        ):
            return ()
        rect = (
            min(start[0], end[0]),
            min(start[1], end[1]),
            max(start[0], end[0]),
            max(start[1], end[1]),
        )

        def inside(point: tuple[float, float]) -> bool:
            return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]

        if self._selection_filter in ("body", "face"):
            groups: dict[BodyId | TopologyId, list[tuple[int, int, int]]] = {}
            body_for_key: dict[BodyId | TopologyId, BodyId] = {}
            for triangle, face_id, body_id in zip(
                snapshot.mesh.triangle_indices,
                snapshot.triangle_face_ids,
                snapshot.triangle_body_ids,
                strict=True,
            ):
                key: BodyId | TopologyId = body_id if self._selection_filter == "body" else face_id
                groups.setdefault(key, []).append(triangle)
                body_for_key[key] = body_id
            targets: list[SelectionState] = []
            for key, triangles in groups.items():
                projected = {
                    index: self.project_world_point(snapshot.mesh.vertices[index])
                    for triangle in triangles
                    for index in triangle
                }
                usable = tuple(point for point in projected.values() if point is not None)
                fully_inside = (
                    bool(usable)
                    and len(usable) == len(projected)
                    and all(inside(point) for point in usable)
                )
                touches = any(inside(point) for point in usable)
                if crossing and not touches:
                    for triangle in triangles:
                        points = tuple(projected[index] for index in triangle)
                        if any(
                            first is not None
                            and second is not None
                            and segment_intersects_rect(first, second, rect)
                            for first, second in (
                                (points[0], points[1]),
                                (points[1], points[2]),
                                (points[2], points[0]),
                            )
                        ):
                            touches = True
                            break
                        if all(point is not None for point in points):
                            triangle_2d = cast(
                                "tuple[tuple[float, float], tuple[float, float], tuple[float, float]]",
                                points,
                            )
                            corners = (
                                (rect[0], rect[1]),
                                (rect[2], rect[1]),
                                (rect[2], rect[3]),
                                (rect[0], rect[3]),
                            )
                            if any(point_in_triangle_2d(corner, triangle_2d) for corner in corners):
                                touches = True
                                break
                if not (touches if crossing else fully_inside):
                    continue
                body_id = body_for_key[key]
                if self._selection_filter == "body":
                    targets.append(SelectionState(snapshot.geometry_revision, "body", (body_id,)))
                else:
                    topology_id = cast(TopologyId, key)
                    targets.append(
                        SelectionState(
                            snapshot.geometry_revision,
                            "face",
                            (body_id,),
                            (topology_id,),
                        )
                    )
            return tuple(targets)

        if self._selection_filter == "edge":
            targets = []
            for edge in snapshot.boundary_edges:
                projected = tuple(self.project_world_point(point) for point in edge.points)
                usable = tuple(point for point in projected if point is not None)
                fully_inside = (
                    bool(usable)
                    and len(usable) == len(projected)
                    and all(inside(point) for point in usable)
                )
                touches = any(inside(point) for point in usable) or any(
                    first is not None
                    and second is not None
                    and segment_intersects_rect(first, second, rect)
                    for first, second in zip(projected, projected[1:], strict=False)
                )
                if touches if crossing else fully_inside:
                    targets.append(
                        SelectionState(
                            snapshot.geometry_revision,
                            "edge",
                            (edge.body_id,),
                            (edge.topology_id,),
                        )
                    )
            return tuple(targets)

        return tuple(
            SelectionState(
                snapshot.geometry_revision,
                "vertex",
                (vertex.body_id,),
                (vertex.topology_id,),
            )
            for vertex in snapshot.vertices
            if (point := self.project_world_point(vertex.point)) is not None and inside(point)
        )

    def _apply_selection_targets(
        self,
        targets: Sequence[SelectionState],
        *,
        toggle: bool,
    ) -> None:
        """Commit pointer selection state only; Document and Bus stay untouched."""
        if toggle:
            selection = (
                self._selection
                if self._selection is not None and self._selection.kind == self._selection_filter
                else None
            )
            for target in targets:
                selection = self._combine_selection_target(selection, target, True)
        elif not targets:
            selection = None
        elif self._selection_filter == "body":
            body_ids = tuple(
                dict.fromkeys(body_id for target in targets for body_id in target.body_ids)
            )
            selection = SelectionState(targets[0].geometry_revision, "body", body_ids)
        else:
            pairs = tuple(
                dict.fromkeys(
                    (body_id, topology_id)
                    for target in targets
                    for body_id, topology_id in zip(
                        target.body_ids, target.topology_ids, strict=True
                    )
                )
            )
            selection = (
                None
                if not pairs
                else SelectionState(
                    targets[0].geometry_revision,
                    self._selection_filter,
                    tuple(body_id for body_id, _topology_id in pairs),
                    tuple(topology_id for _body_id, topology_id in pairs),
                )
            )
        self._selection = selection
        self._preselection = None
        self._current_entity_selected = selection is not None
        self._sync_selection()
        self.current_entity_picked.emit(selection is not None)
        self.selection_changed.emit(selection)

    def state_ordinal(self, state_id: str | None) -> int:
        """Map a state snapshot ID to its command ordinal (-1: unknown)."""
        if state_id is None:
            return -1
        return self._ordinal_of_state.get(state_id, -1)

    def set_orientation(self, orientation: ViewOrientation) -> None:
        """Set a named standard view without changing the camera center or zoom."""
        elevation, azimuth = orientation_angles(orientation)
        self.setCameraPosition(elevation=elevation, azimuth=azimuth)
        self._orientation = orientation
        self._sync_selection()
        self.camera_changed.emit()

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        self.coordinate_indicator.sync_scene()
        super().paintEvent(event)

    @override
    def paintGL(  # noqa: N802
        self,
        region: tuple[int, int, int, int] | None = None,
        viewport: tuple[int, int, int, int] | None = None,
        useItemNames: bool = False,  # noqa: N803
    ) -> None:
        """Keep datum outlines legible even when the GL driver alters line colors."""
        super().paintGL(region=region, viewport=viewport, useItemNames=useItemNames)
        if region is not None or viewport is not None or useItemNames:
            return
        painter = QPainter(self)
        for datum in self._visible_datums():
            frame = datum.frame
            selected = datum.reference == self._selected_datum
            hovered = datum.reference == self._preselected_datum
            emphasis = (
                QColor(235, 135, 10) if selected else QColor(35, 120, 210) if hovered else None
            )

            def line(
                start: Point3, end: Point3, color: QColor, highlight: QColor | None = emphasis
            ) -> None:
                a, b = self.project_world_point(start), self.project_world_point(end)
                if a is not None and b is not None:
                    painter.setPen(QPen(highlight or color, 2))
                    painter.drawLine(QPointF(*a), QPointF(*b))

            if isinstance(frame, RigidFrame):
                for axis, side, color in zip(
                    (frame.x_axis, frame.y_axis, frame.z_axis),
                    (frame.y_axis, frame.x_axis, frame.x_axis),
                    (QColor(190, 35, 35), QColor(30, 145, 55), QColor(35, 75, 210)),
                    strict=True,
                ):
                    origin = frame.origin_mm
                    end = tuple(origin[i] + 20.0 * axis[i] for i in range(3))
                    target: Point3 = (end[0], end[1], end[2])
                    line(origin, target, color)
                    for sign in (-1.0, 1.0):
                        tip = tuple(end[i] - 3.0 * axis[i] + sign * 1.5 * side[i] for i in range(3))
                        line(target, (tip[0], tip[1], tip[2]), color)
            else:
                corners = tuple(
                    frame.local_to_world(point)
                    for point in ((-25, -25), (25, -25), (25, 25), (-25, 25), (-25, -25))
                )
                for a, b in zip(corners, corners[1:], strict=False):
                    line(a, b, QColor(45, 90, 170))
                for axis in (frame.u_axis, frame.v_axis, frame.normal):
                    end = tuple(frame.origin_mm[i] + 12.0 * axis[i] for i in range(3))
                    line(frame.origin_mm, (end[0], end[1], end[2]), QColor(45, 90, 170))
        if self._origin_hotspot is not None:
            point = self.project_world_point(self._origin_hotspot)
            if point is not None:
                painter.setPen(QPen(QColor(240, 110, 0), 3))
                painter.setBrush(QColor(255, 255, 255))
                painter.drawEllipse(QPointF(*point), 7, 7)
        for index, world in enumerate(self._position_points):
            point = self.project_world_point(world)
            if point is not None:
                painter.setPen(QPen(QColor(225, 90, 0) if index == 0 else QColor(35, 100, 210), 3))
                painter.setBrush(QColor(255, 255, 255))
                painter.drawRect(round(point[0]) - 5, round(point[1]) - 5, 10, 10)
        painter.end()

    def set_origin_hotspot(self, point: Point3 | None) -> None:
        """Show the transient coordinate-origin handle in logical pixels."""
        self._origin_hotspot = point
        self.update()

    def initializeGL(self) -> None:  # noqa: N802
        """A recreated widget context needs fresh compiled shader state too."""
        self._workbench_shader = build_workbench_shader()
        if self._mesh_item is not None:
            self._mesh_item.setShader(self._workbench_shader)
        super().initializeGL()

    def set_theme(self, theme: ThemeName) -> None:
        """Apply Qt canvas tokens at the GL boundary and preserve edge contrast."""
        self.setBackgroundColor(theme_tokens(theme).canvas)
        self.coordinate_indicator.set_theme(theme)
        self._edge_color = EDGE_COLOR if theme == "light" else (0.56, 0.67, 0.78, 1.0)
        for item in (self._edge_item, self._mesh_edge_item):
            if item is not None:
                item.setData(color=self._edge_color)
        self.update()

    def orientation(self) -> ViewOrientation | None:
        return self._orientation

    def setCameraPosition(  # noqa: N802
        self,
        pos: QVector3D | None = None,
        distance: float | None = None,
        elevation: float | None = None,
        azimuth: float | None = None,
        rotation: QQuaternion | None = None,
    ) -> None:
        """Keep named Euler views exact and preserve full free-view rotations."""
        if rotation is not None:
            if elevation is not None or azimuth is not None:
                raise ValueError("cannot set both rotation and Euler angles")
            self.opts["rotationMethod"] = "quaternion"
            rotation = rotation.normalized()
        elif elevation is not None or azimuth is not None:
            self.opts["rotationMethod"] = "euler"
        super().setCameraPosition(
            pos=pos, distance=distance, elevation=elevation, azimuth=azimuth, rotation=rotation
        )

    def cameraPosition(self) -> Vector:  # noqa: N802
        """Derive the eye from the same rotation used by rendering and picking."""
        direction = view_camera_basis(self.viewMatrix())[0]
        center: QVector3D = self.opts["center"]
        return Vector(center + QVector3D(*direction) * float(self.opts["distance"]))

    def orbit(self, azim: float, elev: float) -> None:
        """Rotate around screen axes without a world-up lock or pole clamp."""
        rotation: QQuaternion = (
            self.opts["rotation"]
            if self.opts["rotationMethod"] == "quaternion"
            else QQuaternion.fromRotationMatrix(self.viewMatrix().normalMatrix())
        )
        delta = QQuaternion.fromEulerAngles(elev, -azim, 0.0)
        self.setCameraPosition(rotation=(delta * rotation).normalized())
        self._orientation = None
        self.camera_changed.emit()

    def set_projection_mode(self, mode: ProjectionMode) -> None:
        """Switch projection without moving the center or changing the zoom value."""
        if mode not in ("orthographic", "perspective"):
            raise ValueError(f"unsupported projection mode: {mode!r}")
        if mode != self._projection_mode:
            self._projection_mode = mode
            self.update()
            self.camera_changed.emit()

    def projection_mode(self) -> ProjectionMode:
        """Current UI-only projection mode."""
        return self._projection_mode

    def set_selection_filter(self, kind: SelectionKind) -> None:
        """Choose the topology level accepted by future pointer selections."""
        if kind not in ("body", "face", "edge", "vertex"):
            raise ValueError(f"unsupported selection filter: {kind!r}")
        if kind == self._selection_filter:
            return
        self._selection_filter = kind
        self._preselection = None
        self.clear_selection()

    def selection_filter(self) -> SelectionKind:
        """Current view-only selection filter."""
        return self._selection_filter

    def select_body(self, body_id: BodyId) -> bool:
        """Select a current runtime body requested by the structure tree."""
        if self._candidate_snapshot is not None or self._interaction_scene is not None:
            return False
        if not self._source_scene_current():
            return False
        snapshot = self._current_snapshot()
        if snapshot is None or body_id not in snapshot.triangle_body_ids:
            return False
        if self._preview_state_id is not None:
            distance, center = self.camera_state()
            self.show_current_model()
            self.setCameraPosition(pos=QVector3D(*center), distance=distance)
        self.set_selection_filter("body")
        target = SelectionState(snapshot.geometry_revision, "body", (body_id,), ())
        self._apply_selection_targets((target,), toggle=False)
        return True

    def set_modeling_context_active(self, active: bool) -> None:
        """Route viewport right-click/Escape to an active modeling operation."""
        self._modeling_context_active = active
        if not active:
            self._face_origin_snap_enabled = False
            self.coordinate_indicator.set_origin_snap_active(False)
            self.extrude_manipulator.clear()
            self._modeling_interaction_locked = False
            self._modeling_navigation_pos = None
            self._right_press_pos = None
            self._pressed_pos = None

    def set_modeling_interaction_locked(self, locked: bool) -> None:
        """Block picks while a confirmed command is writing, keeping navigation."""

        self._modeling_interaction_locked = locked
        self.extrude_manipulator.set_locked(locked)
        if locked:
            self._pressed_pos = None
            self._right_press_pos = None

    def configure_extrude_handle(
        self, frame: PlanarFaceFrame, distance: float, *, use_face_hit: bool = True
    ) -> None:
        """Anchor on the picked face point; keep the backend's exact normal."""
        frame = self.picked_face_frame(frame) if use_face_hit else frame
        self.extrude_manipulator.configure(frame, distance, self._model_bound_corners())

    def picked_face_frame(
        self, frame: PlanarFaceFrame, *, snap_world_origin: bool = False
    ) -> PlanarFaceFrame:
        hit = self._last_face_hit
        selection = self.selection()
        self._last_face_origin_snapped = False
        if hit is not None and selection is not None and hit[0] in selection.topology_ids:
            if (
                snap_world_origin
                and not self._last_face_snap_bypassed
                and self._last_face_screen is not None
                and self.world_origin_hit(*self._last_face_screen)
            ):
                offset = sum(frame.origin[i] * frame.normal[i] for i in range(3))
                self._last_face_origin_snapped = True
                return PlanarFaceFrame(
                    (offset * frame.normal[0], offset * frame.normal[1], offset * frame.normal[2]),
                    frame.normal,
                )
            offset = sum((hit[1][i] - frame.origin[i]) * frame.normal[i] for i in range(3))
            origin: Point3 = (
                hit[1][0] - offset * frame.normal[0],
                hit[1][1] - offset * frame.normal[1],
                hit[1][2] - offset * frame.normal[2],
            )
            return PlanarFaceFrame(origin, frame.normal)
        return frame

    def face_origin_snapped(self) -> bool:
        """Whether the most recently resolved face point used world-origin alignment."""
        return self._last_face_origin_snapped

    def configure_dimension_handle(self, spec: DimensionHandle, value: float) -> None:
        self.extrude_manipulator.configure_dimension(spec, value, self._model_bound_corners())

    def selected_edge_frame(self) -> PlanarFaceFrame | None:
        """Anchor a radius control on the selected source edge's sampled curve."""
        snapshot, selection = self._interaction_snapshot(), self.selection()
        if snapshot is None or selection is None or selection.kind != "edge":
            return None
        for edge in snapshot.boundary_edges:
            if edge.topology_id not in selection.topology_ids:
                continue
            index = len(edge.points) // 2
            origin = edge.points[index]
            previous = edge.points[index - 1]
            delta = tuple(origin[i] - previous[i] for i in range(3))
            length = float(np.linalg.norm(delta))
            if length > 1e-9:
                tangent = (delta[0] / length, delta[1] / length, delta[2] / length)
                return PlanarFaceFrame(origin, plane_direction(tangent))
        return None

    def _model_bound_corners(self) -> tuple[Point3, ...]:
        if self._mesh is None or not self._mesh.vertices:
            return ()
        vertices = np.asarray(self._mesh.vertices, dtype=np.float64)
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        return tuple(
            (float(x), float(y), float(z))
            for x in (low[0], high[0])
            for y in (low[1], high[1])
            for z in (low[2], high[2])
        )

    def set_fillet_interaction_active(self, active: bool) -> None:
        """Use source-edge selection and CAD-style gestures during a fillet."""
        self._fillet_interaction_active = active
        self._fillet_radius_input_valid = True

    def set_fillet_radius_input_valid(self, valid: bool) -> None:
        """Block edge clicks while the active radius field contains invalid text."""
        self._fillet_radius_input_valid = valid

    def set_placement_context_active(self, active: bool) -> None:
        """Use a click on the global XY work plane to place a new primitive."""
        self._placement_context_active = active
        if not active:
            self.coordinate_indicator.set_origin_snap_active(False)

    def set_face_origin_snap_enabled(self, enabled: bool) -> None:
        """Enable origin feedback while choosing a hole's supporting face."""
        self._face_origin_snap_enabled = enabled
        if not enabled:
            self.coordinate_indicator.set_origin_snap_active(False)

    def selection(self) -> SelectionState | None:
        """Current selection if it still belongs to this geometry revision."""
        snapshot = self._interaction_snapshot()
        if snapshot is None or self._selection is None:
            return None
        if self._selection.geometry_revision != snapshot.geometry_revision:
            return None
        return self._selection

    def camera_distance(self) -> float:
        """Current camera distance from the orbit center in world units."""
        return float(self.opts["distance"])

    def selection_box_active(self) -> bool:
        """Whether a Shift-drag selection rectangle is currently active."""
        return self._rubber_start is not None

    def preselection(self) -> SelectionState | None:
        """Current hover candidate, if any."""
        snapshot = self._interaction_snapshot()
        if snapshot is None or self._preselection is None:
            return None
        if self._preselection.geometry_revision != snapshot.geometry_revision:
            return None
        return self._preselection

    def clear_selection(self) -> None:
        """Clear view selection and highlight state without touching the model."""
        had_selection = self._selection is not None
        self._selection = None
        self._current_entity_selected = False
        self._sync_selection()
        if had_selection:
            self.selection_changed.emit(None)
        self.current_entity_picked.emit(False)

    def set_coordinate_axes_visible(self, visible: bool) -> None:
        """Show or hide the global XYZ indicator as view-only geometry."""
        if visible == self._coordinate_axes_visible:
            return
        self._coordinate_axes_visible = visible
        self.coordinate_indicator.set_origin_visible(visible)
        if not visible:
            self.coordinate_indicator.set_origin_snap_active(False)

    def coordinate_axes_visible(self) -> bool:
        return self._coordinate_axes_visible

    def set_xy_grid_visible(self, visible: bool) -> None:
        """Show or hide the active global XY guide grid."""
        if visible == self._xy_grid_visible:
            return
        self._xy_grid_visible = visible
        if visible:
            self.addItem(self._xy_grid)
        else:
            self.removeItem(self._xy_grid)

    def xy_grid_visible(self) -> bool:
        return self._xy_grid_visible

    def projectionMatrix(self, region: Sequence[int] | None = None) -> QMatrix4x4:  # noqa: N802
        """Keep pyqtgraph's frustum for perspective, or use a matching ortho volume."""
        if self._projection_mode == "perspective":
            return super().projectionMatrix(region)
        device_width = int(self.width() * self.devicePixelRatioF())
        device_height = int(self.height() * self.devicePixelRatioF())
        configured_viewport = self.opts["viewport"]
        viewport = (
            (0, 0, device_width, device_height)
            if configured_viewport is None
            else cast("tuple[int, int, int, int]", configured_viewport)
        )
        if region is None:
            region = (0, 0, device_width, device_height)
        x0, y0, width, height = viewport
        if width <= 0 or height <= 0:
            return super().projectionMatrix(region)
        distance = float(self.opts["distance"])
        fov = radians(float(self.opts["fov"]))
        if distance <= 0.0 or fov <= 0.0:
            return super().projectionMatrix(region)
        half_width = distance * tan(fov / 2.0)
        half_height = half_width * (height / width)
        region_x, region_y, region_width, region_height = region
        left = half_width * (2.0 * (region_x - x0) / width - 1.0)
        right = half_width * (2.0 * (region_x + region_width - x0) / width - 1.0)
        bottom = half_height * (2.0 * (region_y - y0) / height - 1.0)
        top = half_height * (2.0 * (region_y + region_height - y0) / height - 1.0)
        near_clip = distance * 0.001
        far_clip = distance * 1000.0
        matrix = QMatrix4x4()
        matrix.ortho(left, right, bottom, top, near_clip, far_clip)
        return matrix

    def preview_history_feature(self, ordinal: int) -> bool:
        """Display the complete post-command state for an explicit tree pick."""
        state_id = self.history_state_id_for_ordinal(ordinal)
        if state_id is None:
            return False
        return self.preview_history_snapshot(
            state_id, self._port.historical_viewport_data(state_id)
        )

    def history_state_id_for_ordinal(self, ordinal: int) -> str | None:
        """Return a bound history state ID without asking the kernel for a mesh."""
        return next(
            (key for key, value in self._ordinal_of_state.items() if value == ordinal),
            None,
        )

    def preview_history_snapshot(self, state_id: str, snapshot: ViewportData | None) -> bool:
        """Apply an already loaded history snapshot on the owning UI thread."""
        if (
            snapshot is None
            or snapshot.state_id != state_id
            or state_id not in self._ordinal_of_state
        ):
            return False
        had_selection = self._selection is not None
        self._current_entity_selected = False
        self._selection = None
        self._preselection = None
        if had_selection:
            self.selection_changed.emit(None)
        self._preview_state_id = state_id
        self._preview_snapshot = snapshot
        self._candidate_snapshot = None
        self._render_active_state(fit_camera=True)
        self.history_preview_changed.emit(True)
        return True

    def show_current_model(self) -> None:
        """Exit historical preview and restore the current model snapshot."""
        was_previewing = self._preview_state_id is not None
        candidate_camera_state = self._candidate_camera_state
        self._preview_state_id = None
        self._preview_snapshot = None
        self._candidate_snapshot = None
        self._interaction_scene = None
        self._interaction_guard = None
        self._candidate_camera_state = None
        had_selection = self._selection is not None
        self._current_entity_selected = False
        self._selection = None
        self._preselection = None
        if had_selection:
            self.selection_changed.emit(None)
        self._render_active_state(fit_camera=True)
        if candidate_camera_state is not None:
            distance, center = candidate_camera_state
            self.setCameraPosition(
                pos=QVector3D(*center),
                distance=distance,
            )
            self.update()
        if was_previewing:
            self.history_preview_changed.emit(False)

    def _interaction_scene_current(self) -> bool:
        scene = self._interaction_scene
        document = self._document
        return bool(
            scene is not None
            and document is not None
            and document.document_id == scene.document_id
            and document.file_id == scene.file_id
            and document.revision == scene.revision
            and not self._execution_busy
            and self._interaction_guard is not None
            and self._interaction_guard()
        )

    def _source_scene_current(self) -> bool:
        return bool(
            not self._execution_busy
            and self._document is not None
            and self._source_revision == self._document.revision
        )

    def show_interaction_scene(
        self,
        scene: CandidateInteractionScene,
        *,
        session_identity: int,
        is_current: Callable[[], bool],
    ) -> None:
        """Display and pick only a source-bound candidate's own scene."""
        document = self._document
        if (
            document is None
            or not is_current()
            or document.file_id != scene.file_id
            or not scene.matches(
                document.document_id,
                document.revision,
                session_identity,
                scene.candidate_id,
                scene.generation,
            )
        ):
            raise ValueError("candidate scene does not match the current document")
        if scene.viewport is not None:
            self.show_candidate_preview(scene.viewport, preserve_view=True, sketches=scene.sketches)
        else:
            self._candidate_snapshot = None
            self._candidate_sketches = scene.sketches
            self._selection = None
            self._preselection = None
        self._interaction_scene = scene
        self._interaction_guard = is_current
        self._preselected_datum = None
        self._datum_cycle = ()
        self._datum_cycle_position = None
        if all(datum.reference != self._selected_datum for datum in scene.datums):
            self._selected_datum = None
        self._render_active_state()
        if self._mesh is None and scene.datums:
            self.fit_view()

    def show_candidate_preview(
        self,
        snapshot: ViewportData,
        *,
        preserve_view: bool = False,
        sketches: tuple[ViewportSketchData, ...] | None = None,
    ) -> None:
        """Temporarily render candidate geometry without changing the document."""
        was_previewing = self._preview_state_id is not None
        had_selection = self._selection is not None or self._current_entity_selected
        if self._candidate_snapshot is None and not preserve_view:
            self._candidate_camera_state = self.camera_state()
        self._candidate_preserve_view = preserve_view
        self._preview_state_id = None
        self._preview_snapshot = None
        self._candidate_snapshot = snapshot
        self._interaction_scene = None
        self._interaction_guard = None
        self._candidate_sketches = sketches
        if not preserve_view:
            self._selection = None
            self._preselection = None
            self._current_entity_selected = False
        self._render_active_state(fit_camera=not preserve_view)
        if had_selection and not preserve_view:
            self.selection_changed.emit(None)
            self.current_entity_picked.emit(False)
        if was_previewing:
            self.history_preview_changed.emit(False)

    def clear_candidate_preview(self) -> None:
        """Restore the committed model after a temporary candidate preview."""
        if self._candidate_snapshot is None and self._interaction_scene is None:
            return
        camera_state = None if self._candidate_preserve_view else self._candidate_camera_state
        self._candidate_snapshot = None
        self._interaction_scene = None
        self._interaction_guard = None
        self._candidate_sketches = None
        self._candidate_camera_state = None
        self._candidate_preserve_view = False
        self._render_active_state()
        if camera_state is not None:
            distance, center = camera_state
            self.setCameraPosition(pos=QVector3D(*center), distance=distance)
            self.update()

    def history_preview_ordinal(self) -> int | None:
        """The explicitly previewed command ordinal, or ``None`` in current mode."""
        if self._preview_state_id is None:
            return None
        return self._ordinal_of_state.get(self._preview_state_id)

    def displayed_snapshot_id(self) -> str | None:
        """Snapshot ID currently rendered in the main viewport scene."""
        if self._interaction_scene is not None:
            snapshot = self._interaction_scene.viewport
            return snapshot.state_id if snapshot is not None else None
        if self._candidate_snapshot is not None:
            return self._candidate_snapshot.state_id
        return self._preview_state_id or self._current_state_id

    def current_entity_selected(self) -> bool:
        """Whether the current whole-model result is selected."""
        return self.selection() is not None

    def hidden_body_ids(self) -> tuple[BodyId, ...]:
        return tuple(self._hidden_body_ids)

    def visible_body_ids(self) -> tuple[BodyId, ...]:
        """Visible committed bodies; temporary candidate/history previews show all."""
        snapshot = self._current_snapshot()
        return tuple(dict.fromkeys(snapshot.triangle_body_ids)) if snapshot is not None else ()

    def body_visibility_editable(self) -> bool:
        return (
            not self._execution_busy
            and self._candidate_snapshot is None
            and self._preview_state_id is None
        )

    def body_display_hint(self) -> str:
        if self._execution_busy:
            return "正在计算，暂不能改变实体显隐。"
        if not self.body_visibility_editable():
            return "预览显示全部实体；返回当前模型后恢复显隐。"
        return "勾选实体控制显示；隐藏不影响建模和导出。"

    def body_visible(self, identity: BodyId) -> bool:
        """Visibility in the committed model, independent of a temporary preview."""
        return bool(
            self._snapshots
            and identity in self._snapshots[-1].triangle_body_ids
            and identity not in self._hidden_body_ids
        )

    def set_body_visible(self, identity: BodyId, visible: bool) -> bool:
        if (
            not self.body_visibility_editable()
            or not self._snapshots
            or identity not in self._snapshots[-1].triangle_body_ids
        ):
            return False
        if visible:
            self._hidden_body_ids.discard(identity)
        else:
            self._hidden_body_ids.add(identity)
        self._visible_snapshot_cache = None
        if self._selection is not None and identity in self._selection.body_ids:
            self.clear_selection()
        self._preselection = None
        self._redraw_body_visibility()
        return True

    def show_all_bodies(self) -> None:
        if not self.body_visibility_editable():
            return
        self._hidden_body_ids.clear()
        self._visible_snapshot_cache = None
        self._redraw_body_visibility()

    def _redraw_body_visibility(self) -> None:
        distance, center = self.camera_state()
        self._render_active_state()
        self.setCameraPosition(pos=QVector3D(*center), distance=distance)

    def _current_snapshot(self) -> ViewportData | None:
        raw = self._snapshots[-1] if self._snapshots else None
        if raw is None:
            return None
        if self._visibility_source is not raw or self._visible_snapshot_cache is None:
            self._visibility_source = raw
            self._visible_snapshot_cache = visible_body_snapshot(raw, self._hidden_body_ids)
        return self._visible_snapshot_cache

    def _interaction_snapshot(self) -> ViewportData | None:
        scene = self._interaction_scene
        if scene is not None:
            if not self._interaction_scene_current() or scene.viewport is None:
                return None
            return visible_body_snapshot(
                scene.viewport, self._candidate_hidden_bodies(scene.viewport)
            )
        return self._current_snapshot() if self._source_scene_current() else None

    def _candidate_hidden_bodies(self, candidate: ViewportData) -> set[BodyId]:
        source = self._snapshots[-1] if self._snapshots else None
        if source is None:
            return set()
        hidden_results = {
            origin.result
            for origin in source.body_origins
            if origin.body_id in self._hidden_body_ids
        }
        return {
            origin.body_id
            for origin in candidate.body_origins
            if origin.result in hidden_results or origin.body_id in self._hidden_body_ids
        }

    def _render_active_state(self, *, fit_camera: bool = False) -> None:
        """Render either current state or the explicitly previewed state."""
        self.body_display_changed.emit()
        self._sync_datum_items()
        self._sync_sketch_items(
            self._candidate_sketches
            if (self._candidate_snapshot is not None or self._interaction_scene is not None)
            and self._candidate_sketches is not None
            else self._port.sketch_display_data()
        )
        state_id = self.displayed_snapshot_id()
        snapshot = (
            self._interaction_snapshot()
            if self._interaction_scene is not None and self._interaction_scene_current()
            else None
            if self._interaction_scene is not None
            else self._candidate_snapshot
            if self._candidate_snapshot is not None
            else self._preview_snapshot
            if self._preview_state_id is not None
            else self._current_snapshot()
        )
        if snapshot is not None and snapshot.state_id != state_id:
            snapshot = None
        if snapshot is None or not snapshot.mesh.triangle_indices:
            self._mesh = None
            self._clear_items()
            self.update()
            return
        first_scene = self._mesh_item is None
        self._mesh = snapshot.mesh
        self.extrude_manipulator.set_bounds(self._model_bound_corners())
        self._sync_items(self._mesh, snapshot.boundary_edges)
        if self._mesh_item is not None:
            self._mesh_item.setColor(
                PREVIEW_COLOR if self._candidate_snapshot is not None else SHADED_COLOR
            )
        if fit_camera or (first_scene and not self._candidate_preserve_view):
            self.fit_view()
        self._sync_selection()
        self.update()

    def _sync_selection(self) -> None:
        """Draw selected or preselected BREP topology in a reusable overlay."""
        selection = self.selection()
        state = selection or self.preselection()
        overlay_color = HIGHLIGHT_COLOR if selection is not None else PRESELECTION_COLOR
        snapshot = self._interaction_snapshot()
        if (
            state is None
            or snapshot is None
            or self._preview_state_id is not None
            or (self._candidate_snapshot is not None and self._interaction_scene is None)
            or self._mesh is None
        ):
            if self._selection_item is not None:
                self._selection_item.setVisible(False)
            if self._selection_line_item is not None:
                self._selection_line_item.setVisible(False)
            return

        if state.kind in ("body", "face"):
            triangles = tuple(
                triangle
                for triangle, face_id, body_id in zip(
                    snapshot.mesh.triangle_indices,
                    snapshot.triangle_face_ids,
                    snapshot.triangle_body_ids,
                    strict=True,
                )
                if (
                    body_id in state.body_ids
                    if state.kind == "body"
                    else face_id in state.topology_ids
                )
            )
            if not triangles:
                if self._selection_item is not None:
                    self._selection_item.setVisible(False)
                return
            # A selected face is coplanar with the base result. Move only its
            # render overlay slightly toward the camera to avoid depth-buffer
            # ties; the neutral DTO, measurements, and stored geometry stay exact.
            camera_direction, _, _, _ = view_camera_basis(self.viewMatrix())
            depth_bias = max(self.camera_distance() * 0.0005, 0.01)
            overlay_vertices = np.asarray(snapshot.mesh.vertices, dtype=np.float32)
            overlay_vertices += np.asarray(camera_direction, dtype=np.float32) * depth_bias
            mesh_data = MeshData(
                vertexes=overlay_vertices,
                faces=np.asarray(triangles, dtype=np.int32),
            )
            if self._selection_item is None:
                self._selection_item = GLMeshItem(
                    meshdata=mesh_data,
                    color=overlay_color,
                    glOptions="translucent",
                )
                self.addItem(self._selection_item)
            else:
                self._selection_item.setMeshData(meshdata=mesh_data)
                self._selection_item.setColor(overlay_color)
            self._selection_item.setVisible(True)
            if self._selection_line_item is not None:
                self._selection_line_item.setVisible(False)
            return

        line_segments: tuple[tuple[float, float, float], ...]
        if state.kind == "edge":
            line_segments = tuple(
                point
                for edge in snapshot.boundary_edges
                if edge.topology_id in state.topology_ids
                for start, end in zip(edge.points, edge.points[1:], strict=False)
                for point in (start, end)
            )
        else:
            selected_vertices = tuple(
                vertex for vertex in snapshot.vertices if vertex.topology_id in state.topology_ids
            )
            radius = self._vertex_marker_radius()
            line_segments = tuple(
                point
                for vertex in selected_vertices
                for start, end in self._vertex_marker(vertex.point, radius)
                for point in (start, end)
            )
        if not line_segments:
            if self._selection_line_item is not None:
                self._selection_line_item.setVisible(False)
            return
        color = overlay_color
        if self._selection_line_item is None:
            self._selection_line_item = _DepthBiasedLinePlotItem(line_segments, color=color)
            self.addItem(self._selection_line_item)
        elif isinstance(self._selection_line_item, _DepthBiasedLinePlotItem):
            self._selection_line_item.set_positions(line_segments)
        self._selection_line_item.setVisible(True)

    def _vertex_marker_radius(self) -> float:
        width = max(float(self.width()), 1.0)
        distance = float(self.opts["distance"])
        return 8.0 * distance * tan(radians(float(self.opts["fov"])) / 2.0) / width

    @staticmethod
    def _vertex_marker(
        point: tuple[float, float, float], radius: float
    ) -> tuple[tuple[tuple[float, float, float], tuple[float, float, float]], ...]:
        """Three short world axes make an exact vertex visible from any view."""
        x, y, z = point
        return (
            ((x - radius, y, z), (x + radius, y, z)),
            ((x, y - radius, z), (x, y + radius, z)),
            ((x, y, z - radius), (x, y, z + radius)),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Start box selection or delegate camera gestures to pyqtgraph."""
        position = (float(event.position().x()), float(event.position().y()))
        if event.button() == Qt.MouseButton.MiddleButton:
            self._modeling_navigation_pos = position
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.extrude_manipulator.active:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            if self.extrude_manipulator.press(position):
                self._pressed_pos = None
                event.accept()
                return
        if self._fillet_interaction_active or self._modeling_context_active:
            if event.button() == Qt.MouseButton.LeftButton:
                if self._modeling_interaction_locked:
                    event.accept()
                    return
                self._pressed_pos = position
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                self._right_press_pos = position
                self._right_press_started = monotonic()
                event.accept()
                return
        if event.button() == Qt.MouseButton.RightButton and self._modeling_context_active:
            self.context_menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._rubber_start = position
            self._pressed_pos = None
            point = QPoint(round(position[0]), round(position[1]))
            self._rubber_band.setGeometry(QRect(point, point))
            self._rubber_band.show()
            event.accept()
            return
        self._pressed_pos = position
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Select on click or complete a left-to-right/crossing selection box."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._modeling_navigation_pos = None
            self.extrude_manipulator.rebase(
                (float(event.position().x()), float(event.position().y()))
            )
            event.accept()
            return
        if self._fillet_interaction_active and event.button() == Qt.MouseButton.RightButton:
            start = self._right_press_pos
            elapsed = monotonic() - self._right_press_started
            self._right_press_pos = None
            end = (float(event.position().x()), float(event.position().y()))
            if (
                start is not None
                and not self._modeling_interaction_locked
                and elapsed <= 0.35
                and abs(end[0] - start[0]) <= 5.0
                and abs(end[1] - start[1]) <= 5.0
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
            ):
                if self.extrude_manipulator.adjusting:
                    self.extrude_manipulator.finish_gesture()
                else:
                    self.fillet_commit_requested.emit()
            event.accept()
            return
        if self._modeling_context_active:
            if event.button() == Qt.MouseButton.MiddleButton:
                self._modeling_navigation_pos = None
                self.extrude_manipulator.rebase(
                    (float(event.position().x()), float(event.position().y()))
                )
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                start = self._right_press_pos
                elapsed = monotonic() - self._right_press_started
                self._right_press_pos = None
                end = (float(event.position().x()), float(event.position().y()))
                if (
                    start is not None
                    and not self._modeling_interaction_locked
                    and elapsed <= 0.35
                    and abs(end[0] - start[0]) <= 5.0
                    and abs(end[1] - start[1]) <= 5.0
                    and event.modifiers() == Qt.KeyboardModifier.NoModifier
                ):
                    if self.extrude_manipulator.adjusting:
                        self.extrude_manipulator.finish_gesture()
                    else:
                        self.modeling_commit_requested.emit()
                event.accept()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                if self.extrude_manipulator.release():
                    self._pressed_pos = None
                    event.accept()
                    return
                pressed = self._pressed_pos
                self._pressed_pos = None
                pos = (float(event.position().x()), float(event.position().y()))
                if (
                    pressed is not None
                    and not self._modeling_interaction_locked
                    and abs(pos[0] - pressed[0]) <= 5.0
                    and abs(pos[1] - pressed[1]) <= 5.0
                ):
                    if self._placement_context_active:
                        point = self.placement_point_at(
                            *pos,
                            bypass_snap=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                        )
                        if point is None:
                            self.workplane_point_rejected.emit()
                        else:
                            self.workplane_point_picked.emit(
                                point, event.globalPosition().toPoint()
                            )
                    elif self._preview_state_id is None and (
                        not self._fillet_interaction_active or self._fillet_radius_input_valid
                    ):
                        self.pick_at(
                            *pos,
                            toggle=self._fillet_interaction_active
                            or bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
                            bypass_origin_snap=bool(
                                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                            ),
                        )
                event.accept()
                return
        if self._fillet_interaction_active and event.button() == Qt.MouseButton.LeftButton:
            pressed = self._pressed_pos
            self._pressed_pos = None
            pos = (float(event.position().x()), float(event.position().y()))
            if (
                pressed is not None
                and abs(pos[0] - pressed[0]) <= 5.0
                and abs(pos[1] - pressed[1]) <= 5.0
                and self._preview_state_id is None
                and self._fillet_radius_input_valid
            ):
                self.pick_at(*pos, toggle=True)
            event.accept()
            return
        if self._rubber_start is not None:
            start = self._rubber_start
            self._rubber_start = None
            self._rubber_band.hide()
            end = (float(event.position().x()), float(event.position().y()))
            targets = self.targets_in_screen_rect(
                start,
                end,
                crossing=end[0] < start[0],
            )
            self._apply_selection_targets(
                targets,
                toggle=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
            )
            event.accept()
            return
        pressed = self._pressed_pos
        self._pressed_pos = None
        super().mouseReleaseEvent(event)
        if pressed is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = (float(event.position().x()), float(event.position().y()))
        if abs(pos[0] - pressed[0]) > 3.0 or abs(pos[1] - pressed[1]) > 3.0:
            return
        if self._placement_context_active:
            point = self.placement_point_at(
                *pos, bypass_snap=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
            if point is None:
                self.workplane_point_rejected.emit()
                event.accept()
                return
            self.workplane_point_picked.emit(point, event.globalPosition().toPoint())
            event.accept()
            return
        hits = self.datum_targets_at(*pos)
        identities = tuple(hit.reference for hit in hits)
        if identities:
            model_hit = (
                self.selection_target_at(*pos, self._selection_filter)
                if self._datum_pick_filter is None
                else None
            )
            candidate_count = len(identities) + (1 if model_hit is not None else 0)
            if (
                identities == self._datum_cycle
                and self._datum_cycle_position is not None
                and dist(pos, self._datum_cycle_position) <= 3.0
            ):
                self._datum_cycle_index = (self._datum_cycle_index + 1) % candidate_count
            else:
                self._datum_cycle_index = 0
            self._datum_cycle = identities
            self._datum_cycle_position = pos
            if self._datum_cycle_index < len(identities):
                hit = hits[self._datum_cycle_index]
                short_id = (hit.reference.source_instance_id or "world")[:8]
                self.setToolTip(
                    f"{hit.name} · {hit.reference.kind} · {short_id} "
                    f"({self._datum_cycle_index + 1}/{candidate_count}，再次点击切换)"
                )
                self.select_datum(identities[self._datum_cycle_index])
            else:
                self._selected_datum = None
                self._sync_datum_items()
                self.pick_at(*pos)
            event.accept()
            return
        if self._preview_state_id is None and self._datum_pick_filter is None:
            self.pick_at(
                *pos,
                toggle=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
            )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Update the rubber band or hover preselection without moving geometry."""
        position = (float(event.position().x()), float(event.position().y()))
        self.coordinate_indicator.set_origin_snap_active(
            (
                self._placement_context_active
                or (
                    self._face_origin_snap_enabled
                    and self._candidate_snapshot is None
                    and self._interaction_scene is None
                    and self._preview_state_id is None
                    and self._source_scene_current()
                )
            )
            and event.buttons() == Qt.MouseButton.NoButton
            and not bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            and self.world_origin_hit(*position)
        )
        if self._modeling_navigation_pos is not None:
            previous = self._modeling_navigation_pos
            dx = position[0] - previous[0]
            dy = position[1] - previous[1]
            self._modeling_navigation_pos = position
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.pan(dx, dy, 0, relative="view")
            else:
                self.orbit(-dx, dy)
            self._sync_selection()
            event.accept()
            return
        if self._right_press_pos is None and self.extrude_manipulator.move(position):
            event.accept()
            return
        if (
            self._modeling_context_active
            and self._pressed_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            event.accept()
            return
        if self._modeling_context_active and self._right_press_pos is not None:
            event.accept()
            return
        if (
            not self._modeling_context_active
            and self._pressed_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            start = self._pressed_pos
            if abs(position[0] - start[0]) > 5 or abs(position[1] - start[1]) > 5:
                self._rubber_start = start
                self._pressed_pos = None
                self._rubber_band.show()
            else:
                event.accept()
                return
        if self._rubber_start is not None:
            start = QPoint(round(self._rubber_start[0]), round(self._rubber_start[1]))
            end = QPoint(round(position[0]), round(position[1]))
            self._rubber_band.setGeometry(QRect(start, end).normalized())
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            # Including a still-held button after Esc cancelled a selection box.
            # Left-drag never delegates to pyqtgraph's orbit/pan bindings.
            event.accept()
            return
        if event.buttons() == Qt.MouseButton.NoButton and not self._modeling_context_active:
            hits = self.datum_targets_at(*position)
            hovered = hits[0].reference if hits else None
            if hovered != self._preselected_datum:
                self._preselected_datum = hovered
                self.setToolTip(
                    f"{hits[0].name} · {hits[0].reference.kind} · "
                    f"{(hits[0].reference.source_instance_id or 'world')[:8]} "
                    "（重复点击可切换重叠对象）"
                    if hits
                    else ""
                )
                self._sync_datum_items()
            if hovered is not None:
                self._preselection = None
                self._sync_selection()
                super().mouseMoveEvent(event)
                return
        if (
            event.buttons() == Qt.MouseButton.NoButton
            and self._preview_state_id is None
            and (
                self._candidate_snapshot is None
                or self._modeling_context_active
                or self._fillet_interaction_active
            )
        ):
            preselection = self.selection_target_at(*position, self._selection_filter)
            if preselection != self._preselection:
                self._preselection = preselection
                self._sync_selection()
        super().mouseMoveEvent(event)
        if event.buttons() != Qt.MouseButton.NoButton:
            self._sync_selection()

    @override
    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self._preselected_datum = None
        self.coordinate_indicator.set_origin_snap_active(False)
        self.setToolTip("")
        self._sync_datum_items()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Escape cancels a selection box or clears view selection/preselection."""
        if self.extrude_manipulator.handle_key(event):
            event.accept()
            return
        if self._modeling_context_active:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._fillet_interaction_active:
                    self.fillet_commit_requested.emit()
                else:
                    self.modeling_commit_requested.emit()
                event.accept()
                return
            if self._fillet_interaction_active and event.key() == Qt.Key.Key_R:
                self.radius_edit_requested.emit("")
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                self.escape_pressed.emit()
                event.accept()
                return
            text = event.text()
            if (
                self._fillet_interaction_active
                and len(text) == 1
                and (text.isdigit() or text == ".")
            ):
                self.radius_edit_requested.emit(text)
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape:
            if self._modeling_context_active:
                self.escape_pressed.emit()
                event.accept()
                return
            if self._rubber_start is not None:
                self._rubber_start = None
                self._rubber_band.hide()
                event.accept()
                return
            if self._selection is not None or self._preselection is not None:
                self._preselection = None
                self.clear_selection()
                event.accept()
                return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Double middle-click explicitly fits the model during a fillet."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self.fit_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    # Scene construction
    # ------------------------------------------------------------------

    def _visible_datums(self) -> tuple[ViewportDatum, ...]:
        if self._interaction_scene is not None:
            datums = self._interaction_scene.datums if self._interaction_scene_current() else ()
        elif (
            self._preview_state_id is not None
            or self._candidate_snapshot is not None
            or not self._source_scene_current()
            or not isinstance(self._port, SpatialDatumPort)
        ):
            datums = ()
        else:
            datums = self._port.datum_display_data()
        return tuple(datum for datum in datums if datum.reference not in self._hidden_datums)

    def interaction_datums(self) -> tuple[ViewportDatum, ...]:
        """Visible datum anchors in the same active interaction context."""
        return self._visible_datums()

    def interaction_snap_anchors(self) -> tuple[ViewportSnapAnchor, ...]:
        """Return exact anchors for the displayed scene, never a hidden source scene."""
        if self._interaction_scene is not None:
            if not self._interaction_scene_current():
                return ()
            snapshot = self._interaction_scene.viewport
            hidden: set[BodyId] = (
                self._candidate_hidden_bodies(snapshot) if snapshot is not None else set()
            )
            return tuple(
                anchor
                for anchor in self._interaction_scene.snap_anchors
                if anchor.body_id not in hidden
            )
        if self._preview_state_id is not None or not isinstance(self._port, SpatialDatumPort):
            return ()
        if not self._source_scene_current():
            return ()
        return tuple(
            anchor
            for anchor in self._port.snap_anchor_data()
            if anchor.body_id not in self._hidden_body_ids
        )

    def set_workplane_grid(self, frame: WorkPlaneFrame | None, spacing: float) -> None:
        """Show a transient UV grid without changing model or global grid state."""
        if self._workplane_grid is not None:
            self.removeItem(self._workplane_grid)
            self._workplane_grid = None
        if frame is None:
            return
        points = [
            frame.local_to_world((u * spacing, v * spacing))
            for u in range(-10, 11)
            for v in range(-10, 11)
        ]
        self._workplane_grid = _ContextScatterPlotItem(
            pos=np.asarray(points, dtype=np.float32),
            color=(0.25, 0.35, 0.45, 0.55),
            size=2.0,
            pxMode=True,
            glOptions="translucent",
        )
        self.addItem(self._workplane_grid)

    def set_position_markers(self, point: Point3 | None, source: Point3 | None = None) -> None:
        """Display a transient location and, when projected, its source point."""
        if point is None:
            if self._position_marker is not None:
                self.removeItem(self._position_marker)
                self._position_marker = None
            if self._position_projection_line is not None:
                self.removeItem(self._position_projection_line)
                self._position_projection_line = None
            self._position_points = ()
            return
        self._position_points = (point,) if source is None else (point, source)
        positions = np.asarray(self._position_points, dtype=np.float32)
        colors = np.asarray(
            ((1.0, 0.55, 0.05, 1.0),)
            if source is None
            else ((1.0, 0.55, 0.05, 1.0), (0.2, 0.45, 1.0, 1.0)),
            dtype=np.float32,
        )
        if self._position_marker is None:
            self._position_marker = _ContextScatterPlotItem(
                pos=positions, color=colors, size=9, pxMode=True
            )
            self.addItem(self._position_marker)
        else:
            self._position_marker.setData(pos=positions, color=colors)
        if source is None:
            if self._position_projection_line is not None:
                self.removeItem(self._position_projection_line)
                self._position_projection_line = None
        elif self._position_projection_line is None:
            self._position_projection_line = GLLinePlotItem(
                pos=positions, color=(0.2, 0.45, 1.0, 1.0), width=1
            )
            self.addItem(self._position_projection_line)
        else:
            self._position_projection_line.setData(pos=positions)

    def position_marker_points(self) -> tuple[Point3, ...]:
        return self._position_points

    def look_at_workplane(self, frame: WorkPlaneFrame) -> None:
        """Orient the camera along the plane normal while leaving its frame untouched."""
        matrix = QMatrix4x4()
        matrix.setRow(0, QVector4D(*frame.u_axis, 0))
        matrix.setRow(1, QVector4D(*frame.v_axis, 0))
        matrix.setRow(2, QVector4D(*frame.normal, 0))
        self.setCameraPosition(rotation=QQuaternion.fromRotationMatrix(matrix.normalMatrix()))
        self._orientation = None
        self.camera_changed.emit()

    def datum_display_count(self) -> int:
        """Number of visible datum objects, independent of solid geometry."""
        return len(self._visible_datums())

    def preselected_datum(self) -> SpatialReference | None:
        reference = self._preselected_datum
        return (
            reference
            if any(datum.reference == reference for datum in self._visible_datums())
            else None
        )

    def hidden_datum_references(self) -> tuple[SpatialReference, ...]:
        return tuple(self._hidden_datums)

    def set_datum_visible(self, reference: SpatialReference, visible: bool) -> None:
        if visible:
            self._hidden_datums.discard(reference)
        else:
            self._hidden_datums.add(reference)
        self._render_active_state()

    def set_datum_pick_filter(self, references: frozenset[SpatialReference] | None) -> None:
        """Limit parent picks to allowed, already confirmed outputs."""
        self._datum_pick_filter = references
        self._preselected_datum = None
        self._datum_cycle = ()
        self._sync_datum_items()

    def datum_pick_filter(self) -> frozenset[SpatialReference] | None:
        return self._datum_pick_filter

    def select_datum(self, reference: SpatialReference) -> None:
        """Select a datum by stable identity, including a hidden tree object."""
        if self._datum_pick_filter is not None and reference not in self._datum_pick_filter:
            return
        if self._interaction_scene is not None:
            datums = self._interaction_scene.datums if self._interaction_scene_current() else ()
        elif self._source_scene_current() and isinstance(self._port, SpatialDatumPort):
            datums = self._port.datum_display_data()
        else:
            datums = ()
        if all(datum.reference != reference for datum in datums):
            return
        if self._selection is not None:
            self.clear_selection()
        self._selected_datum = reference
        self.datum_selection_changed.emit(reference)
        self._render_active_state()

    def datum_targets_at(self, x: float, y: float) -> tuple[ViewportDatum, ...]:
        """Return every visible datum hit, with deterministic identity ordering."""
        ray = self.camera_ray(x, y)
        hits: list[tuple[float, float, str, ViewportDatum]] = []
        for datum in self._visible_datums():
            if (
                self._datum_pick_filter is not None
                and datum.reference not in self._datum_pick_filter
            ):
                continue
            if isinstance(datum.frame, RigidFrame):
                projected = self.project_world_point(datum.frame.origin_mm)
                screen_distance = dist(projected, (x, y)) if projected is not None else float("inf")
                if projected is not None:
                    for axis in (datum.frame.x_axis, datum.frame.y_axis, datum.frame.z_axis):
                        end = (
                            datum.frame.origin_mm[0] + 20.0 * axis[0],
                            datum.frame.origin_mm[1] + 20.0 * axis[1],
                            datum.frame.origin_mm[2] + 20.0 * axis[2],
                        )
                        projected_end = self.project_world_point(end)
                        if projected_end is None:
                            continue
                        dx, dy = projected_end[0] - projected[0], projected_end[1] - projected[1]
                        length_squared = dx * dx + dy * dy
                        fraction = (
                            max(
                                0.0,
                                min(
                                    1.0,
                                    ((x - projected[0]) * dx + (y - projected[1]) * dy)
                                    / length_squared,
                                ),
                            )
                            if length_squared
                            else 0.0
                        )
                        screen_distance = min(
                            screen_distance,
                            dist(
                                (x, y), (projected[0] + fraction * dx, projected[1] + fraction * dy)
                            ),
                        )
                if screen_distance <= 12:
                    depth = dist(ray[0], datum.frame.origin_mm) if ray is not None else 0.0
                    hits.append(
                        (
                            screen_distance,
                            depth,
                            datum.reference.source_instance_id or "",
                            datum,
                        )
                    )
            elif ray is not None:
                point = intersect_plane(ray[0], ray[1], datum.frame)
                if point is not None:
                    u, v = datum.frame.world_to_local(point)
                    if abs(u) <= 25.0 and abs(v) <= 25.0:
                        hits.append(
                            (
                                0.0,
                                dist(ray[0], point),
                                datum.reference.source_instance_id or "",
                                datum,
                            )
                        )
        return tuple(item[3] for item in sorted(hits, key=lambda item: item[:3]))

    def _clear_datum_items(self) -> None:
        for item in self._datum_items:
            self.removeItem(item)
        self._datum_items.clear()

    def _sync_datum_items(self) -> None:
        self._clear_datum_items()
        for datum in self._visible_datums():
            frame = datum.frame
            if isinstance(frame, RigidFrame):
                origin = frame.origin_mm
                for axis, color, axis_name in zip(
                    (frame.x_axis, frame.y_axis, frame.z_axis),
                    ((0.85, 0.2, 0.2, 1.0), (0.2, 0.65, 0.25, 1.0), (0.2, 0.35, 0.9, 1.0)),
                    ("X", "Y", "Z"),
                    strict=True,
                ):
                    if datum.reference == self._selected_datum:
                        color = (1.0, 0.65, 0.05, 1.0)
                    elif datum.reference == self._preselected_datum:
                        color = (0.35, 0.7, 1.0, 1.0)
                    end = tuple(origin[i] + 20.0 * axis[i] for i in range(3))
                    line = GLLinePlotItem(
                        pos=np.asarray((origin, end), dtype=np.float32),
                        color=np.asarray((color, color), dtype=np.float32),
                        width=2,
                    )
                    self._datum_items.append(line)
                    self.addItem(line)
                    side = frame.y_axis if axis_name == "X" else frame.x_axis
                    arrow = tuple(
                        tuple(end[i] - 3.0 * axis[i] + sign * 1.5 * side[i] for i in range(3))
                        for sign in (-1.0, 1.0)
                    )
                    arrow_item = GLLinePlotItem(
                        pos=np.asarray((arrow[0], end, arrow[1]), dtype=np.float32),
                        color=np.asarray((color, color, color), dtype=np.float32),
                        width=2,
                    )
                    self._datum_items.append(arrow_item)
                    self.addItem(arrow_item)
                    axis_label = GLTextItem(
                        pos=list(end), text=axis_name, color=tuple(round(c * 255) for c in color)
                    )
                    self._datum_items.append(axis_label)
                    self.addItem(axis_label)
            else:
                corners = tuple(
                    frame.local_to_world(point)
                    for point in ((-25, -25), (25, -25), (25, 25), (-25, 25), (-25, -25))
                )
                line = GLLinePlotItem(
                    pos=np.asarray(corners, dtype=np.float32),
                    color=(1.0, 0.65, 0.05, 1.0)
                    if datum.reference == self._selected_datum
                    else (0.35, 0.7, 1.0, 1.0)
                    if datum.reference == self._preselected_datum
                    else (0.25, 0.5, 0.8, 0.8),
                    width=2,
                )
                self._datum_items.append(line)
                self.addItem(line)
                for axis, axis_name in zip(
                    (frame.u_axis, frame.v_axis, frame.normal), ("U", "V", "N"), strict=True
                ):
                    end = tuple(frame.origin_mm[i] + 12.0 * axis[i] for i in range(3))
                    direction_line = GLLinePlotItem(
                        pos=np.asarray((frame.origin_mm, end), dtype=np.float32),
                        color=(0.2, 0.35, 0.7, 1.0),
                        width=2,
                    )
                    axis_label = GLTextItem(pos=list(end), text=axis_name, color=(51, 89, 179, 255))
                    self._datum_items.extend((direction_line, axis_label))
                    self.addItem(direction_line)
                    self.addItem(axis_label)
            label = GLTextItem(pos=list(frame.origin_mm), text=datum.name, color=(38, 64, 102, 255))
            self._datum_items.append(label)
            self.addItem(label)

    def _clear_items(self) -> None:
        for item in (
            self._mesh_item,
            self._edge_item,
            self._mesh_edge_item,
            self._selection_item,
            self._selection_line_item,
        ):
            if item is not None:
                self.removeItem(item)
        self._mesh_item = None
        self._edge_item = None
        self._mesh_edge_item = None
        self._selection_item = None
        self._selection_line_item = None
        self._mesh_data = None

    def _clear_sketch_items(self) -> None:
        for item in self._sketch_items:
            self.removeItem(item)
        self._sketch_items.clear()
        for item in self._sketch_point_items:
            self.removeItem(item)
        self._sketch_point_items.clear()
        for item in self._sketch_dimension_items:
            self.removeItem(item)
        self._sketch_dimension_items.clear()
        self._sketch_dimension_label_count = 0

    def _sync_sketch_items(self, sketches: Sequence[ViewportSketchData]) -> None:
        self._clear_sketch_items()
        for sketch in sketches:
            if sketch.points:
                item = _ContextScatterPlotItem(
                    pos=np.asarray([point.point for point in sketch.points], dtype=np.float32),
                    color=np.asarray(
                        [
                            (*[value / 255.0 for value in point.layer.color_rgb], 1.0)
                            for point in sketch.points
                        ],
                        dtype=np.float32,
                    ),
                    size=9,
                    pxMode=True,
                )
                self._sketch_point_items.append(item)
                self.addItem(item)
            for curve in sketch.curves:
                positions = tuple(
                    point
                    for start, end in zip(curve.points, curve.points[1:], strict=False)
                    for point in (start, end)
                )
                if not positions:
                    continue
                if curve.construction:
                    color = (0.62, 0.70, 0.76, 1.0)
                else:
                    red, green, blue = curve.layer.color_rgb
                    color = (red / 255.0, green / 255.0, blue / 255.0, 1.0)
                item = _DepthBiasedLinePlotItem(positions, color=color)
                self._sketch_items.append(item)
                self.addItem(item)
            dimensions = sketch.dimensions
            if (
                sketch.sketch_id == self._active_draft_sketch_id
                and self._candidate_snapshot is None
                and self._interaction_scene is None
            ):
                dimensions = ()
            for dimension in dimensions:
                red, green, blue = dimension.color_rgb
                luminance = (2126 * red + 7152 * green + 722 * blue) / 10000.0
                if luminance >= 190:
                    red, green, blue = (48, 58, 70)
                font = QFont("Sans Serif")
                font.setPointSizeF(max(8.0, min(24.0, 10.0 * dimension.scale**0.5)))
                item = GLTextItem(
                    pos=dimension.position,
                    text=dimension.text,
                    color=(red, green, blue, 255),
                    font=font,
                    glOptions="translucent",
                )
                self._sketch_dimension_items.append(item)
                self._sketch_dimension_label_count += 1
                self.addItem(item)

    def _sync_items(
        self,
        mesh: Tessellation,
        boundary_edges: Sequence[ViewportBoundaryEdge],
    ) -> None:
        mesh_data = MeshData(
            vertexes=np.asarray(mesh.vertices, dtype=np.float32),
            faces=np.asarray(mesh.triangle_indices, dtype=np.int32),
        )
        self._mesh_data = mesh_data
        if self._mesh_item is None:
            self._mesh_item = GLMeshItem(
                meshdata=mesh_data,
                shader=self._workbench_shader,
                color=SHADED_COLOR,
                glOptions="opaque",
            )
            self.addItem(self._mesh_item)
        else:
            self._mesh_item.setMeshData(meshdata=mesh_data)
        if self._selection_item is not None:
            self._selection_item.setMeshData(meshdata=mesh_data)
        segments = tuple(
            point
            for boundary in boundary_edges
            for start, end in zip(boundary.points, boundary.points[1:], strict=False)
            for point in (start, end)
        )
        if segments:
            if self._edge_item is None:
                self._edge_item = _DepthBiasedLinePlotItem(segments, color=self._edge_color)
                self.addItem(self._edge_item)
            else:
                if isinstance(self._edge_item, _DepthBiasedLinePlotItem):
                    self._edge_item.set_positions(segments)
        elif self._edge_item is not None:
            self.removeItem(self._edge_item)
            self._edge_item = None
        if self._render_mode == "mesh-diagnostic":
            diagnostic_segments = self._mesh_edge_segments(mesh)
            if self._mesh_edge_item is None:
                self._mesh_edge_item = _DepthBiasedLinePlotItem(
                    diagnostic_segments, color=self._edge_color
                )
                self.addItem(self._mesh_edge_item)
            elif isinstance(self._mesh_edge_item, _DepthBiasedLinePlotItem):
                self._mesh_edge_item.set_positions(diagnostic_segments)
        self._apply_render_mode()

    @staticmethod
    def _mesh_edge_segments(mesh: Tessellation) -> tuple[tuple[float, float, float], ...]:
        return tuple(
            mesh.vertices[index] for edge in unique_edges(mesh.triangle_indices) for index in edge
        )

    def _apply_render_mode(self) -> None:
        """Show BREP boundaries and tessellation diagnostics independently."""
        if self._mesh_item is not None:
            self._mesh_item.setVisible(self._render_mode != "engineering-wireframe")
        if self._edge_item is not None:
            self._edge_item.setVisible(
                self._render_mode in ("shaded-edges", "engineering-wireframe")
            )
        if self._mesh_edge_item is not None and self._render_mode != "mesh-diagnostic":
            self.removeItem(self._mesh_edge_item)
            self._mesh_edge_item = None

    # ------------------------------------------------------------------
    # Presentation controls
    # ------------------------------------------------------------------

    def set_shaded(self, shaded: bool) -> None:
        """视图 menu slot: shaded body on, or wireframe only."""
        self.set_render_mode("shaded-edges" if shaded else "engineering-wireframe")

    def set_render_mode(self, mode: RenderMode) -> None:
        """Set one explicit shaded, BREP, wireframe or mesh-diagnostic mode."""
        if mode not in (
            "shaded",
            "shaded-edges",
            "engineering-wireframe",
            "mesh-diagnostic",
        ):
            raise ValueError(f"unsupported render mode: {mode!r}")
        self._render_mode = mode
        self._apply_render_mode()
        if mode == "mesh-diagnostic" and self._mesh is not None and self._mesh_edge_item is None:
            self._mesh_edge_item = _DepthBiasedLinePlotItem(
                self._mesh_edge_segments(self._mesh),
                color=self._edge_color,
            )
            self.addItem(self._mesh_edge_item)
        self.update()

    def is_shaded(self) -> bool:
        return self._render_mode != "engineering-wireframe"

    def render_mode(self) -> RenderMode:
        """Return the active, UI-only render mode."""
        return self._render_mode

    def mesh_visible(self) -> bool:
        """Whether the shaded body item is on screen (empty scene → False)."""
        return self._mesh_item is not None and self._mesh_item.visible()

    def boundary_lines_visible(self) -> bool:
        """Whether the engineering BREP boundary layer is visible."""
        return self._edge_item is not None and self._edge_item.visible()

    def mesh_diagnostic_visible(self) -> bool:
        """Whether the triangulation-edge diagnostic layer is visible."""
        return self._mesh_edge_item is not None and self._mesh_edge_item.visible()

    def fit_view(self) -> None:
        """Point the camera at the model bbox from its bounding-sphere radius.

        Use the active projection and viewport aspect ratio so the bounding
        sphere stays inside both projected axes. Mouse interaction afterwards
        is free — this runs for the first scene and from the fit-view action.
        """
        vertices: list[Point3] = [] if self._mesh is None else list(self._mesh.vertices)
        for datum in self._visible_datums():
            frame = datum.frame
            if isinstance(frame, RigidFrame):
                vertices.append(frame.origin_mm)
                for axis in (frame.x_axis, frame.y_axis, frame.z_axis):
                    vertices.append(
                        cast("Point3", tuple(frame.origin_mm[i] + 20 * axis[i] for i in range(3)))
                    )
            else:
                vertices.extend(
                    frame.local_to_world(point)
                    for point in ((-25, -25), (25, -25), (25, 25), (-25, 25))
                )
        if not vertices:
            return
        self.fit_world_points(vertices)

    def fit_world_points(
        self, vertices: Sequence[Point3], *, margin: float = FIT_VIEW_MARGIN
    ) -> None:
        """Fit a specified set of world points using the active projection."""
        if not vertices:
            return
        points = np.asarray(vertices, dtype=np.float64)
        lower = points.min(axis=0)
        upper = points.max(axis=0)
        center = (lower + upper) / 2.0
        radius = float(np.linalg.norm(upper - lower) / 2.0)
        if radius <= 0.0:
            return
        fov_degrees = float(self.opts["fov"])
        aspect = max(self.width(), 1) / max(self.height(), 1)
        half_horizontal_fov = radians(fov_degrees) / 2.0
        if self._projection_mode == "orthographic":
            distance = radius * max(1.0, aspect) / tan(half_horizontal_fov)
        else:
            half_vertical_fov = atan(tan(half_horizontal_fov) / aspect)
            distance = radius / sin(min(half_horizontal_fov, half_vertical_fov))
        distance *= margin
        self.setCameraPosition(
            pos=QVector3D(float(center[0]), float(center[1]), float(center[2])),
            distance=distance,
        )
        self._sync_selection()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        """Retain selection overlay depth bias while the camera zooms."""
        super().wheelEvent(event)
        self.extrude_manipulator.rebase((float(event.position().x()), float(event.position().y())))
        self._sync_selection()

    def camera_state(self) -> tuple[float, tuple[float, float, float]]:
        """(distance, center) as plain floats — what ``fit_view`` moves."""
        center: QVector3D = self.opts["center"]
        return (
            float(self.opts["distance"]),
            (float(center.x()), float(center.y()), float(center.z())),
        )
