"""Spike: flange acceptance part via build123d command-style modeling.

Validates the geom-layer foundation planned for MyCAD phase 0:
- imperative construction (maps directly to future commands)
- boolean cut + polar hole pattern
- STEP/STL export and STEP round-trip
- deterministic geometric assertions

NOT product code: lives in /tmp, planner verification only.
"""
import math
from pathlib import Path

from build123d import (
    BuildPart,
    Cylinder,
    GeomType,
    Mode,
    PolarLocations,
    export_step,
    export_stl,
    import_step,
)

OUT = Path(__file__).parent

# Flange: OD 80, thickness 8, center bore 20, 4x holes d6 on PCD 50
with BuildPart() as flange:
    Cylinder(radius=40, height=8)
    Cylinder(radius=10, height=20, mode=Mode.SUBTRACT)  # center bore
    with PolarLocations(radius=25, count=4):
        Cylinder(radius=3, height=20, mode=Mode.SUBTRACT)  # bolt holes

part = flange.part

# --- geometric assertions -------------------------------------------------
expected_vol = math.pi * 8 * (40**2 - 10**2 - 4 * 3**2)
assert abs(part.volume - expected_vol) < 1e-6, (part.volume, expected_vol)
assert len(part.solids()) == 1, len(part.solids())

# cylindrical faces: outer + 5 through-holes = 6
cyl_faces = part.faces().filter_by(GeomType.CYLINDER)
assert len(cyl_faces) == 6, len(cyl_faces)

bbox = part.bounding_box()
assert abs(bbox.size.Z - 8) < 1e-9, bbox.size.Z
assert abs(bbox.size.X - 80) < 1e-9 and abs(bbox.size.Y - 80) < 1e-9

# --- export + round-trip --------------------------------------------------
step_path = OUT / "flange.step"
stl_path = OUT / "flange.stl"
export_step(part, step_path)
export_stl(part, stl_path)
assert step_path.stat().st_size > 10_000, step_path.stat().st_size
assert stl_path.stat().st_size > 1_000, stl_path.stat().st_size

reloaded = import_step(str(step_path))
assert len(reloaded.solids()) == 1
assert abs(reloaded.volume - part.volume) < 1e-6

print(f"SPIKE_OK volume={part.volume:.4f} expected={expected_vol:.4f}")
print(f"STEP={step_path.stat().st_size}B STL={stl_path.stat().st_size}B")
print("round-trip volume match: yes")
