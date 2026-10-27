# P2-33 Solver Research and Restricted Prototype

Status: research gate complete; P2-33 implementation remains pending.

## Research result

- Selected candidate: `planegcs==0.9.6`, a Python wrapper around FreeCAD PlaneGCS. Its API exposes point/line/circle/arc primitives, common geometric constraints, a degrees-of-freedom query, solve status, and diagnosis. The wrapper states LGPL-2.1-or-later.
- Published wheels cover CPython 3.12–3.14 on Windows x86-64 and manylinux x86-64. The source build requires Eigen3 and Boost. The project currently supports Python 3.12–3.14, so the published Python versions align; no aarch64 wheel or T2 source build was verified.
- SolveSpace was not selected because its upstream contribution guide states GPLv3-or-later.
- Decision and integration gates are in [ADR-010](../../docs/adr/ADR-010-sketch-solver-integration.md).

## Prototype observations

Executed an isolated `uv run --no-project --with planegcs==0.9.6` probe on Linux x86-64 / CPython 3.12.3. It did not alter the project dependency files.

| Case | Observed result |
|---|---|
| Fixed origin, horizontal line, 10 mm endpoint distance; initial endpoint at `(8, 2)` | `Success`, 0 DOF, endpoint `(10, 0)` |
| Same constraints with an added vertical relation | `Failed`; diagnosis listed horizontal, distance, and vertical relations as conflicting |
| Two fresh solver instances with identical geometry and constraints | Identical endpoint solution `(10, 0)` |
| Same constraints seeded with endpoint at `(-8, 2)` | `Success`, 0 DOF, endpoint `(-10, 0)` |

The last two outcomes establish a necessary product rule: preserve the accepted geometry as the next solve's seed, display solver status alongside degrees of freedom, and do not claim a zero-DOF state is unique. A failed preview must not replace accepted sketch geometry.

## References

- [planegcs 0.9.6 package and wheel matrix](https://pypi.org/project/planegcs/)
- [planegcs upstream API and license](https://github.com/spookylukey/planegcs)
- [FreeCAD PlaneGCS source license header](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Sketcher/App/planegcs/GCS.h)
- [FreeCAD source license documentation](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/License.md)
- [SolveSpace license statement](https://github.com/solvespace/solvespace/blob/master/CONTRIBUTING.md)
