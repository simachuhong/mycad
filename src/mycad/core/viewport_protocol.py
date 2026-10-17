# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Viewport port: the third dependency inversion (phase 1, todo 2).

Core holds only ``ViewportData`` and the ``ViewportPort`` Protocol; it
never imports ``mycad.geom``, ``numpy`` or Qt. The concrete per-feature
mesh extraction is implemented by the BuildKernel adapter in
``mycad.geom`` (todo 3) and consumed by the UI package. Wireframe edges
are derived on the render side by deduplicating triangle edges, so the
protocol carries no edge data; rendering semantics (colours, lights)
stay out of core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from mycad.core.geometry_types import Tessellation


@dataclass(frozen=True)
class ViewportData:
    """One per-feature mesh snapshot, in feature-history order.

    ``feature_id`` identifies the snapshot as ``"<command id>:<ordinal>"``
    (snapshot semantics are implemented by the geom adapter in todo 3).
    ``mesh`` reuses ``mycad.core.geometry_types.Tessellation`` verbatim —
    vertex/index invariants are validated in its own ``__post_init__``,
    and the vertex/index fields are deliberately NOT redefined here so
    the DTO keeps a single definition point. ``normals`` is optional:
    the UI may derive or compute them when a visual style needs them.
    """

    feature_id: str
    mesh: Tessellation
    normals: tuple[tuple[float, float, float], ...] = field(default=())


@runtime_checkable
class ViewportPort(Protocol):
    """Surface that hands per-feature snapshots to the UI layer."""

    def viewport_data(self) -> tuple[ViewportData, ...]:
        """Return one snapshot per ``feature_history`` ordinal.

        The tuple is the whole-model state after the last executed
        command; an empty document yields an empty tuple.
        """
        ...
