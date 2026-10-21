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
from math import radians, sin
from typing import TYPE_CHECKING

import numpy as np
from pyqtgraph.opengl import GLLinePlotItem, GLMeshItem, GLViewWidget, MeshData
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D

from mycad.core.signals import SignalName

if TYPE_CHECKING:
    from mycad.core.geometry_types import Tessellation
    from mycad.core.persistence import LoadedDocument
    from mycad.core.viewport_protocol import ViewportPort

#: UI 初稿 §9: 工业灰蓝, 视口区域更亮更干净 (docks are the darker layer).
VIEWPORT_BACKGROUND: tuple[float, float, float, float] = (0.18, 0.21, 0.26, 1.0)
#: Machined-part steel tone for the shaded body.
SHADED_COLOR: tuple[float, float, float, float] = (0.72, 0.75, 0.80, 1.0)
#: Dark blue-grey edges: readable over the body and on the bare background.
EDGE_COLOR: tuple[float, float, float, float] = (0.16, 0.19, 0.24, 1.0)

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
    untouched; ``fit_view()`` is the only camera this class drives. No picking
    (todo 10), no antialiasing or material work (UI 初稿 §9 asks for an
    industrial grey-blue base tone only).
    """

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

    # ------------------------------------------------------------------
    # Document binding and refresh coalescing
    # ------------------------------------------------------------------

    def bind_document(self, loaded: LoadedDocument) -> None:
        """Subscribe the refresh union to ``loaded`` and render it once."""
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

    def refresh(self) -> None:
        """Re-read ``viewport_data()`` and rebuild the scene synchronously."""
        self._rebuilds += 1
        snapshots = self._port.viewport_data()
        self._snapshot_count = len(snapshots)
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

    def rebuild_count(self) -> int:
        """How many rebuilds ran — the observable that proves coalescing."""
        return self._rebuilds

    def snapshot_count(self) -> int:
        """How many kernel snapshots the last refresh saw (todo 10 hooks)."""
        return self._snapshot_count

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
