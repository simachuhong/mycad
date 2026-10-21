# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo 9: the 3D viewport — a pyqtgraph.opengl surface fed by the kernel.

The scene shows exactly ONE snapshot: the whole-model state after the last
executed command (``viewport_data()[-1]``), drawn as one shaded MeshData
plus its deduplicated triangle edges. Intermediate snapshots deliberately
stay off-screen — todo 10 picks them up for selection/tree linkage — so the
render cost never grows with the history length.

Refresh is driven by the same core signal union todo 8 subscribes to: one
command emits only pre/post_command (core/bus.py:101/115, and the batch
success path emits no geometry_rebuilt), while undo/redo/replay/rollback emit
only geometry_rebuilt (core/bus.py:165). Subscribing to one family misses
the other, so all six converge on ``_schedule_refresh()``, which coalesces a
whole event-loop turn into a single rebuild — a batch renders its final
snapshot exactly once.

No ``mycad.geom`` import: geometry arrives through the core ``ViewportPort``
protocol, so this module never touches the CAD backend (tests/test_layering
bans it) and stays on the data side of the boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import partial
from math import radians, sin, tan
from typing import TYPE_CHECKING

import numpy as np
from pyqtgraph.opengl import GLLinePlotItem, GLMeshItem, GLViewWidget, MeshData
from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QMouseEvent, QVector3D

from mycad.core.signals import SignalName

if TYPE_CHECKING:
    from mycad.core.document import Document
    from mycad.core.geometry_types import Tessellation
    from mycad.core.persistence import LoadedDocument
    from mycad.core.viewport_protocol import ViewportData, ViewportPort

#: UI 初稿 §9: 工业灰蓝, 视口区域更亮更干净 (docks are the darker layer).
VIEWPORT_BACKGROUND: tuple[float, float, float, float] = (0.18, 0.21, 0.26, 1.0)
#: Machined-part steel tone for the shaded body.
SHADED_COLOR: tuple[float, float, float, float] = (0.72, 0.75, 0.80, 1.0)
#: Dark blue-grey edges: readable over the body and on the bare background.
EDGE_COLOR: tuple[float, float, float, float] = (0.16, 0.19, 0.24, 1.0)
#: Todo 10 highlight: translucent amber overlay on the selected feature mesh.
HIGHLIGHT_COLOR: tuple[float, float, float, float] = (1.0, 0.62, 0.10, 0.45)

#: Extra room around the bounding sphere so the model never touches the border.
FIT_VIEW_MARGIN: float = 1.2

#: The todo-8 union. Order is documentation only; membership is what matters.
#: A single command (post_command) and a replay/undo (geometry_rebuilt) must
#: both land, plus the data-plane signals that change what a rebuild would
#: produce (command_amended / metadata_changed / named_group ±).
REFRESH_SIGNALS: tuple[SignalName, ...] = (
    "post_command",
    "geometry_rebuilt",
    "command_amended",
    "metadata_changed",
    "named_group_added",
    "named_group_removed",
)


#: Möller–Trumbore epsilon: thickness below this counts as parallel.
RAY_EPSILON: float = 1e-9


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
    nearest: float | None = None
    vertices = mesh.vertices
    for tri in mesh.triangle_indices:
        t = ray_triangle_hit(
            origin,
            direction,
            vertices[tri[0]],
            vertices[tri[1]],
            vertices[tri[2]],
        )
        if t is not None and (nearest is None or t < nearest):
            nearest = t
    return nearest


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


class GLViewport(GLViewWidget):
    """Central viewport: kernel snapshots in, one shaded+wireframe scene out.

    Mouse rotate/pan/wheel-zoom are ``GLViewWidget``'s built-ins and are kept
    untouched; ``fit_view()`` is the only camera this class drives. No
    antialiasing or material work (UI 初稿 §9 asks for an industrial
    grey-blue base tone only).

    Todo 10 picking is the math fallback the plan pins for the
    unstable-offscreen-readback case: a click becomes a camera ray (pinhole
    model, fov from the widget) and every snapshot mesh is intersected
    without drawing anything — front-most snapshot along the ray wins, exact
    depth-buffer semantics minus the GL readback. The picked ``feature_id``
    maps to its command ordinal by position (snapshot order equals
    ``Document.commands`` order); the highlight is the selected snapshot's
    mesh as a translucent amber overlay (a destructive command's snapshot is
    its own post-execution state, so tree clicks highlight exactly that).
    """

    # Click on a feature: its command ordinal; -1 = empty space (cleared).
    feature_picked = Signal(int)

    def __init__(self, *, viewport_port: ViewportPort) -> None:
        super().__init__()
        self.setBackgroundColor(VIEWPORT_BACKGROUND)
        self.setMinimumSize(160, 120)
        self._port = viewport_port
        self._mesh_item: GLMeshItem | None = None
        self._edge_item: GLLinePlotItem | None = None
        self._mesh: Tessellation | None = None
        self._shaded = True
        self._rebuilds = 0
        self._snapshot_count = 0
        self._refresh_pending = False
        self._disposed = False
        # Parented so a pending rebuild dies with the widget: an orphaned
        # singleShot outlives the C++ object and would call refresh() on
        # deleted shiboken memory.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._run_scheduled_refresh)
        # The signal bus holds subscribers weakly (core/signals.py), so the
        # per-signal adapters need strong owners until the next bind/close.
        self._adapters: list[Callable[[Mapping[str, object]], None]] = []
        # Todo 10: feature_id -> command ordinal, rebuilt from the bound
        # document on every refresh (snapshot order == commands order).
        self._document: Document | None = None
        self._ordinal_of_feature: dict[str, int] = {}
        self._highlight_item: GLMeshItem | None = None
        self._highlight_feature: str | None = None
        self._pressed_pos: tuple[float, float] | None = None

    # ------------------------------------------------------------------
    # Document binding and refresh coalescing
    # ------------------------------------------------------------------

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Subscribe the refresh union to ``loaded`` and render it once."""
        self._document = loaded.document
        self._adapters.clear()
        events = loaded.document.events
        for name in REFRESH_SIGNALS:
            adapter = partial(self._on_refresh_signal, name)
            self._adapters.append(adapter)
            events.subscribe(name, adapter)
        self.refresh()

    def _on_refresh_signal(self, name: str, payload: Mapping[str, object]) -> None:
        """Signal adapter: the name/payload are context, the rebuild is not."""
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        """Collapse every signal of one event-loop turn into one rebuild."""
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._refresh_timer.start()

    def _run_scheduled_refresh(self) -> None:
        self._refresh_pending = False
        if self._disposed:
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
        self._disposed = True
        self._refresh_timer.stop()
        self._adapters.clear()
        self._ordinal_of_feature = {}
        self._highlight_feature = None

    def refresh(self) -> None:
        """Re-read ``viewport_data()`` and rebuild the scene synchronously."""
        self._rebuilds += 1
        snapshots = self._port.viewport_data()
        self._snapshot_count = len(snapshots)
        self._rebuild_feature_map(snapshots)
        if not snapshots:
            self._mesh = None
            self._clear_items()
            return
        first_scene = self._mesh_item is None
        self._mesh = snapshots[-1].mesh
        self._sync_items(self._mesh)
        if first_scene:
            self.fit_view()
        self.update()
        self._sync_highlight()

    def rebuild_count(self) -> int:
        """How many rebuilds ran — the observable that proves coalescing."""
        return self._rebuilds

    def snapshot_count(self) -> int:
        """How many kernel snapshots the last refresh saw (todo 10 hooks)."""
        return self._snapshot_count

    def snapshots(self) -> tuple[ViewportData, ...]:
        """The per-feature snapshot list backing picking/highlight."""
        return self._port.viewport_data()

    # ------------------------------------------------------------------
    # Todo 10: picking and highlight
    # ------------------------------------------------------------------

    def _rebuild_feature_map(self, snapshots: Sequence[ViewportData]) -> None:
        """Snapshot order equals Document.commands order — zip into a map.

        A size mismatch (document replay and viewport read diverge) drops
        the map instead of guessing: highlighting degrades to nothing, no
        wrong ordinal is ever produced.
        """
        self._ordinal_of_feature = {}
        if self._document is None:
            return
        commands = tuple(self._document.commands)
        if len(commands) != len(snapshots):
            return
        self._ordinal_of_feature = {
            snapshot.feature_id: int(command.ordinal)
            for snapshot, command in zip(snapshots, commands, strict=True)
        }

    def camera_ray(
        self, x: float, y: float
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        """Pinhole ray (origin, normalized direction) through widget pixel.

        Uses the same fov/center/distance model ``fit_view`` writes into the
        widget; up is world +Z, matching GLViewWidget's elevation/azimuth
        camera. Returns ``None`` when there is no scene or the window has no
        size yet.
        """
        if "pos" not in self.opts:  # never fitted / no scene yet
            return None
        distance = float(self.opts["distance"])
        center: QVector3D = self.opts["center"]
        pos: QVector3D = self.opts["pos"]
        width, height = float(self.width()), float(self.height())
        if width <= 0.0 or height <= 0.0 or distance <= 0.0:
            return None
        view = np.array(
            [center.x() - pos.x(), center.y() - pos.y(), center.z() - pos.z()],
            dtype=np.float64,
        )
        norm = float(np.linalg.norm(view))
        if norm <= 0.0:
            return None
        forward = view / norm
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(forward, world_up)
        right_norm = float(np.linalg.norm(right))
        if right_norm <= 0.0:  # camera looking straight along +Z is degenerate
            return None
        right = right / right_norm
        up = np.cross(right, forward)
        fov = radians(float(self.opts["fov"]))
        half_height = tan(fov / 2.0) * distance
        half_width = half_height * (width / height)
        px = ((2.0 * x / width) - 1.0) * half_width
        py = (1.0 - (2.0 * y / height)) * half_height
        direction = forward + right * px + up * py
        dnorm = float(np.linalg.norm(direction))
        if dnorm <= 0.0:
            return None
        origin = (pos.x(), pos.y(), pos.z())
        unit = direction / dnorm
        return origin, (float(unit[0]), float(unit[1]), float(unit[2]))

    def pick_feature_at_ray(
        self, origin: tuple[float, float, float], direction: tuple[float, float, float]
    ) -> str | None:
        """Front-most snapshot along the ray — its ``feature_id`` (or None)."""
        nearest: tuple[float, str] | None = None
        for snapshot in self._port.viewport_data():
            t = ray_mesh_hit(origin, direction, snapshot.mesh)
            if t is not None and (nearest is None or t < nearest[0]):
                nearest = (t, snapshot.feature_id)
        return None if nearest is None else nearest[1]

    def pick_at(self, x: float, y: float) -> int:
        """Click pixel -> command ordinal (-1 for empty space / no scene)."""
        ray = self.camera_ray(x, y)
        feature_id = None if ray is None else self.pick_feature_at_ray(ray[0], ray[1])
        return self.feature_ordinal(feature_id)

    def feature_ordinal(self, feature_id: str | None) -> int:
        """Map a snapshot ``feature_id`` to its command ordinal (-1: unknown)."""
        if feature_id is None:
            return -1
        return self._ordinal_of_feature.get(feature_id, -1)

    def highlight_feature(self, ordinal: int | None) -> None:
        """选中反馈：该 feature 的快照 mesh 以琥珀色半透明叠显。

        破坏性命令（如 cut）的快照即其执行后状态（kernel 侧 A5 语义），
        所以树节点点击高亮的就是该命令完成后的几何。``None`` 清除高亮。
        """
        self._highlight_feature = None
        for feature_id, mapped in self._ordinal_of_feature.items():
            if mapped == ordinal:
                self._highlight_feature = feature_id
                break
        if self._highlight_item is not None:
            self.removeItem(self._highlight_item)
            self._highlight_item = None
        self._sync_highlight()
        self.update()

    def highlight_ordinal(self) -> int | None:
        """Currently highlighted command ordinal, or ``None``."""
        if self._highlight_feature is None:
            return None
        return self._ordinal_of_feature.get(self._highlight_feature)

    def _sync_highlight(self) -> None:
        """Re-add the highlight overlay after a scene rebuild (or drop it)."""
        if self._highlight_item is not None:
            return
        if self._highlight_feature is None or self._mesh is None:
            return
        mesh = next(
            (
                snapshot.mesh
                for snapshot in self._port.viewport_data()
                if snapshot.feature_id == self._highlight_feature
            ),
            None,
        )
        if mesh is None:  # feature vanished (undo/replay) — stay unhighlighted
            self._highlight_feature = None
            return
        self._highlight_item = GLMeshItem(
            meshdata=MeshData(
                vertexes=np.asarray(mesh.vertices, dtype=np.float32),
                faces=np.asarray(mesh.triangle_indices, dtype=np.int32),
            ),
            shader="shaded",
            color=HIGHLIGHT_COLOR,
            glOptions="translucent",
        )
        self.addItem(self._highlight_item)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Record press position: a press→release pair without movement is a
        click pick, not a rotate/pan drag (built-ins keep handling those)."""
        self._pressed_pos = (float(event.position().x()), float(event.position().y()))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Emit ``feature_picked`` only for a real click (no drag)."""
        pressed = self._pressed_pos
        self._pressed_pos = None
        super().mouseReleaseEvent(event)
        if pressed is None:
            return
        pos = (float(event.position().x()), float(event.position().y()))
        if abs(pos[0] - pressed[0]) > 3.0 or abs(pos[1] - pressed[1]) > 3.0:
            return
        self.feature_picked.emit(self.pick_at(*pos))

    # ------------------------------------------------------------------
    # Scene construction
    # ------------------------------------------------------------------

    def _clear_items(self) -> None:
        for item in (self._mesh_item, self._edge_item):
            if item is not None:
                self.removeItem(item)
        self._mesh_item = None
        self._edge_item = None

    def _sync_items(self, mesh: Tessellation) -> None:
        mesh_data = MeshData(
            vertexes=np.asarray(mesh.vertices, dtype=np.float32),
            faces=np.asarray(mesh.triangle_indices, dtype=np.int32),
        )
        if self._mesh_item is None:
            self._mesh_item = GLMeshItem(
                meshdata=mesh_data,
                shader="shaded",
                color=SHADED_COLOR,
                glOptions="opaque",
            )
            self.addItem(self._mesh_item)
        else:
            self._mesh_item.setMeshData(meshdata=mesh_data)
        segments = [
            mesh.vertices[index] for edge in unique_edges(mesh.triangle_indices) for index in edge
        ]
        if self._edge_item is None:
            self._edge_item = GLLinePlotItem(
                pos=segments,
                mode="lines",
                color=EDGE_COLOR,
                width=1.0,
                glOptions="opaque",
            )
            self.addItem(self._edge_item)
        else:
            self._edge_item.setData(pos=segments)
        self._apply_shading()

    def _apply_shading(self) -> None:
        """Shaded = body + edges; wireframe = edges only."""
        if self._mesh_item is not None:
            self._mesh_item.setVisible(self._shaded)
        if self._edge_item is not None:
            self._edge_item.setVisible(True)

    # ------------------------------------------------------------------
    # Presentation controls
    # ------------------------------------------------------------------

    def set_shaded(self, shaded: bool) -> None:
        """视图 menu slot: shaded body on, or wireframe only."""
        self._shaded = shaded
        self._apply_shading()
        self.update()

    def is_shaded(self) -> bool:
        return self._shaded

    def mesh_visible(self) -> bool:
        """Whether the shaded body item is on screen (empty scene → False)."""
        return self._mesh_item is not None and self._mesh_item.visible()

    def fit_view(self) -> None:
        """Point the camera at the model bbox from its bounding-sphere radius.

        Distance = radius / sin(fov/2) is the exact distance at which the
        bounding sphere fills the vertical field of view; FIT_VIEW_MARGIN
        then leaves a border. Mouse interaction afterwards is free — this is
        only called on the first scene and by the 视图 menu action.
        """
        if self._mesh is None or not self._mesh.vertices:
            return
        points = np.asarray(self._mesh.vertices, dtype=np.float64)
        lower = points.min(axis=0)
        upper = points.max(axis=0)
        center = (lower + upper) / 2.0
        radius = float(np.linalg.norm(upper - lower) / 2.0)
        if radius <= 0.0:
            return
        fov_degrees = float(self.opts["fov"])
        distance = radius / sin(radians(fov_degrees) / 2.0) * FIT_VIEW_MARGIN
        self.setCameraPosition(
            pos=QVector3D(float(center[0]), float(center[1]), float(center[2])),
            distance=distance,
        )

    def camera_state(self) -> tuple[float, tuple[float, float, float]]:
        """(distance, center) as plain floats — what ``fit_view`` moves."""
        center: QVector3D = self.opts["center"]
        return (
            float(self.opts["distance"]),
            (float(center.x()), float(center.y()), float(center.z())),
        )
