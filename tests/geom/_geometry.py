# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared kernel-built geometry fixtures for the geom test package."""

from __future__ import annotations

import math

from mycad.geom.kernel import BuildKernel

FLANGE_OUTER_RADIUS = 40.0
FLANGE_THICKNESS = 8.0
FLANGE_BORE_RADIUS = 10.0
FLANGE_HOLE_RADIUS = 3.0
FLANGE_HOLE_PCD_RADIUS = 25.0


def flange_volume_formula() -> float:
    """Analytic flange volume — the only truth source (never hand-typed)."""

    return (
        math.pi
        * FLANGE_THICKNESS
        * (FLANGE_OUTER_RADIUS**2 - FLANGE_BORE_RADIUS**2 - 4 * FLANGE_HOLE_RADIUS**2)
    )


def build_flange(kernel: BuildKernel) -> None:
    """OD80 / bore20 / thick8 / 4x d6 on PCD50, built purely via kernel.apply."""

    kernel.apply(
        "feature.cylinder",
        {
            "radius": FLANGE_OUTER_RADIUS,
            "height": FLANGE_THICKNESS,
            "mode": "new",
        },
    )
    kernel.apply(
        "feature.cylinder",
        {"radius": FLANGE_BORE_RADIUS, "height": 20.0, "mode": "cut"},
    )
    for x, y in (
        (FLANGE_HOLE_PCD_RADIUS, 0.0),
        (0.0, FLANGE_HOLE_PCD_RADIUS),
        (-FLANGE_HOLE_PCD_RADIUS, 0.0),
        (0.0, -FLANGE_HOLE_PCD_RADIUS),
    ):
        kernel.apply(
            "feature.cylinder",
            {
                "radius": FLANGE_HOLE_RADIUS,
                "height": 20.0,
                "mode": "cut",
                "center": (x, y, 0.0),
            },
        )


def build_stacked_blocks(kernel: BuildKernel) -> None:
    """20x20x5 base (z in [0,5]) with a 10x10x5 block stacked on top (z in [5,10]).

    Exactly two +Z outward horizontal faces with different areas
    (300 and 100 after the fuse) — the #round9-2 multi-face construction.
    """

    kernel.apply(
        "feature.box",
        {"size_x": 20.0, "size_y": 20.0, "size_z": 5.0, "center": (0.0, 0.0, 2.5), "mode": "new"},
    )
    kernel.apply(
        "feature.box",
        {"size_x": 10.0, "size_y": 10.0, "size_z": 5.0, "center": (0.0, 0.0, 7.5), "mode": "add"},
    )


def build_offset_equal_tops(kernel: BuildKernel) -> None:
    """Two disjoint 10x10x5 blocks whose top faces have EQUAL area (100) —
    the lexicographic (x, y, z) tiebreak construction (centers at x=-10/+10)."""

    kernel.apply(
        "feature.box",
        {"size_x": 10.0, "size_y": 10.0, "size_z": 5.0, "center": (-10.0, 0.0, 2.5), "mode": "new"},
    )
    kernel.apply(
        "feature.box",
        {"size_x": 10.0, "size_y": 10.0, "size_z": 5.0, "center": (10.0, 0.0, 2.5), "mode": "add"},
    )
