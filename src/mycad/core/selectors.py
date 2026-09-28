# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral selector descriptors (Phase 0).

Selectors describe which face(s) or edge(s) of a solid a future command
will target. They are **deliberately** free of numeric indices, ranks, or
positions: downstream code must resolve a selector to concrete topology
through the (later wave) geometry adapter. The structural absence of an
``index`` / ``rank`` field is asserted by ``tests/test_layering.py`` and
``tests/core/test_selectors.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Face selectors
# ---------------------------------------------------------------------------

AxisLiteral = Literal["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
SurfaceLiteral = Literal["plane", "cylinder"]


@dataclass(frozen=True)
class FaceSelector:
    """Pick a face by surface kind and optional axis alignment.

    ``axis`` only applies to planar faces (``surface="plane"``). Cylindrical
    faces are picked solely by ``surface`` at this stage; finer-grained
    cylindrical selection (radius band, axis direction) lands in a later
    wave via the geometry adapter.
    """

    surface: SurfaceLiteral
    axis: AxisLiteral | None = None
    rank: int | None = None


CurveLiteral = Literal["line", "circle"]


@dataclass(frozen=True)
class EdgeSelector:
    """Pick an edge by the surfaces it lies between.

    ``parent_faces`` is required: an edge must belong to at least one face.
    A line vs circle hint is available via ``curve`` for downstream
    disambiguation; this descriptor carries no positional data of its own.
    """

    parent_faces: tuple[FaceSelector, ...]
    curve: CurveLiteral | None = None


__all__ = [
    "FaceSelector",
    "EdgeSelector",
    "AxisLiteral",
    "SurfaceLiteral",
    "CurveLiteral",
]
