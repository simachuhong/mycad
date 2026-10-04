"""Spike: pin exact build123d 0.11.1 fillet signature + box/cylinder cut mode.

Evidence for plan T5 (no API exploration left to the implementer).
"""

import inspect
import math

from build123d import (
    Axis,
    Box,
    BuildPart,
    Cylinder,
    Edge,
    GeomType,
    Mode,
    Part,
    fillet,
)

print("build123d top-level fillet signature:", inspect.signature(fillet))
print("Part.fillet signature:", inspect.signature(Part.fillet))

# --- Algebra mode: box + fillet on selected edges ---
base = Box(10, 10, 10)
print("Part.fillet doc first line:", (Part.fillet.__doc__ or "").strip().splitlines()[0])

# top-level functional form: fillet(*objects, radius)
try:
    top_edges = base.edges().group_by(Axis.Z)[-1]
    rounded = fillet(top_edges, radius=1.0)
    print(
        "functional fillet OK; solids:",
        len(rounded.solids()),
        "vol:",
        round(rounded.volume, 4),
    )
except Exception as exc:  # noqa: BLE001 - spike probe
    print("functional fillet FAILED:", type(exc).__name__, exc)

# method form
try:
    base2 = Box(10, 10, 10)
    top_edges2 = base2.edges().group_by(Axis.Z)[-1]
    rounded2 = base2.fillet(1.0, top_edges2)
    print("method fillet OK; vol:", round(rounded2.volume, 4))
except Exception as err:  # noqa: BLE001
    print("method fillet(radius, edges) FAILED:", type(err).__name__, err)

try:
    base3 = Box(10, 10, 10)
    top_edges3 = base3.edges().group_by(Axis.Z)[-1]
    rounded3 = base3.fillet(top_edges3, 1.0)
    print("method fillet(edges, radius) OK; vol:", round(rounded3.volume, 4))
except Exception as err:  # noqa: BLE001
    print("method fillet(edges, radius) FAILED:", type(err).__name__, err)

# --- Builder mode: cylinder with Mode.SUBTRACT (confirms box/cylinder cut) ---
with BuildPart() as cut_demo:
    Cylinder(40, 8)
    Cylinder(10, 20, mode=Mode.SUBTRACT)
print("cylinder subtract OK; vol:", round(cut_demo.part.volume, 6))
expect_cyl = math.pi * 8 * (40**2 - 10**2)
print("expected:", round(expect_cyl, 6))

with BuildPart() as box_cut:
    Box(20, 20, 10)
    Box(5, 5, 30, mode=Mode.SUBTRACT)
print("box subtract OK; vol:", round(box_cut.part.volume, 6), "expected:", 20 * 20 * 10 - 5 * 5 * 10)

# edge selector for fillet on flange: top outer circle edge = circle edge
with BuildPart() as fl:
    Cylinder(40, 8)
    Cylinder(10, 20, mode=Mode.SUBTRACT)
circles = fl.edges().filter_by(GeomType.CIRCLE)
print("flange circle edges:", len(circles), "radii:", sorted({round(e.radius, 3) for e in circles}))
outer_top = [e for e in circles if abs(e.radius - 40) < 1e-6]
print("outer circle edges:", len(outer_top))
