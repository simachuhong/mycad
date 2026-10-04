# Phase 0 / T2 evidence — geom kernel adapter (Wave 1)

**Task**: T2 — sealed build123d kernel adapter (BuildKernel: box/cylinder in
new/add/cut, version gate, FaceSelector/EdgeSelector resolution per the 6
plan rules, neutral DTO mass properties + in-memory tessellation, layering
guard extension).
**Plan**: `.omo/plans/phase0-mvp.md` lines 191–221 (todo), 26–58 (guardrails),
75–91 (verification), 550–662 (Appendix A descriptor shapes).
**UTC timestamp**: 2026-10-04T09:03:46Z (finisher pass; original delivery by a
prior agent that died mid-refactor, completed per re-diagnosis below).
**Environment**: Linux x86_64, Python 3.12.3, uv; build123d 0.11.1 pinned,
OCP 7.9.3.1.1.

## 0. Finisher re-diagnosis (this session)

The prior agent died mid-refactor of the tessellate path. Fresh diagnosis from
code, not from its notes:

- `tests/geom/test_kernel_query.py` failed 3 tessellation tests with
  `NameError: name 'deepcopy' is not defined` at `src/mycad/geom/query.py:92` —
  the re-mesh-on-deepcopy design was written (docstring + call) but the import
  was never added. Fix: `from copy import deepcopy` (one line). All 3 tests
  went green; no other behavioural change was needed.
- Ruff: unused `from OCP.BRepTools import BRepTools` (dead after the refactor)
  removed via `--fix`; 2 files reformatted.
- basedpyright strict: 28 errors finished to 0 (details §5). Notably the
  version-gate callable was renamed `_assert_b123d_version` →
  `assert_b123d_version` (public) so tests can import it without
  `reportPrivateUsage`; the plan asked for "a directly-testable callable
  (e.g. _assert_b123d_version())" — the leading underscore was the problem,
  the testability requirement is unchanged and still met.

## 1. Deepcopy re-mesh design — empirical justification (adversarial probe)

OCCT's incremental mesher never refines an already-triangulated face, so
re-`tessellate()`ing the same Part with a finer tolerance returns STALE
triangle counts. Probe on the flange shape (outer Ø80×8 − bore Ø20 − 4×Ø6
PCD50), angular 30°, chord 10→5 mm:

```
same part coarse->fine: 512 -> 512   (STALE — cached triangulation reused)
deepcopy per call:      512 -> 592   (correct refinement)
fresh part fine only:   592          (ground truth)
```

`build_tessellation` therefore meshes a `deepcopy(part)` on every call; the
kernel's stored Part is never mutated and repeated calls at different
tolerances always reflect the requested tolerance.

## 2. Manual-QA channel (real-surface flange proof)

Script: `/tmp/opencode/t2_manual_qa.py` (temp, deleted after capture).
Construction per the spike: `feature.cylinder r=40 h=8 mode=new`;
`r=10 h=20 mode=cut` (through); 4× `r=3 h=20 mode=cut` at (±25,0,0),(0,±25,0).

```
volume          = 36794.333159 mm^3
expected        = 36794.333159 mm^3  (pi*h*(R^2-r^2-4*hole^2))
volume delta    = 7.276e-12 mm^3  (tol 1e-6)
solid_count     = 1
cyl_face_count  = 6 (expect 6: bore + 4 holes + rim)
bbox            = BoundingBox(xmin=-40.0, ymin=-40.0, zmin=-4.0, xmax=40.0, ymax=40.0, zmax=4.0)  (expect 80x80x8)
center_of_mass  = (-3.74e-15, -2.57e-15, -1.11e-16)
(plane,+Z) rank=0 area = 4599.291645 mm^2 (largest flange face)
(cylinder,None) candidates = 6 (expect 6)
```

Volume is asserted against the closed-form formula computed in the test
(`math.pi * 8 * (40**2 - 10**2 - 4*3**2)`), never a hand-typed rounded
constant and never an echo of implementation output.

### Tessellation monotonicity numbers

```
chord=10.00mm angular= 30.0deg -> triangles=  512 vertices=  508
chord= 5.00mm angular= 30.0deg -> triangles=  592 vertices=  588
chord= 2.50mm angular= 30.0deg -> triangles=  592 vertices=  588   (plateau)
chord= 5.00mm angular= 15.0deg -> triangles= 1008 vertices= 1004
chord= 5.00mm angular=  7.5deg -> triangles= 1392 vertices= 1388
chord= 2.50mm angular=  7.5deg -> triangles= 2000 vertices= 1996
```

Halving the chord tolerance strictly increases triangles whenever the linear
deflection is the binding constraint (512→592 at 10→5 mm; 1392→2000 at
2.5 mm once the angular deflection is tightened to 7.5°). The 5→2.5 mm
plateau at 30° is correct OCCT behaviour, not a caching bug: with a 30°
angular deflection the cylindrical faces are already segmented to their
angular floor, so the finer chord changes nothing. Each constraint
monotonically increases the mesh when it is the binding one. Vertex ranges
stay within the bbox: x ∈ [−40.000, 40.000], z ∈ [−4.000, 4.000].

### Empty-geometry semantics (stale_state probe)

```
after reset: solid_count=0 volume=0.0 bbox=None com=(0.0, 0.0, 0.0)
```

Defined state, not an exception — matches the plan.

## 3. Layering-guard tamper proof (red → restore → green)

Baseline `uv run pytest tests/test_layering.py -q` → 3 passed. Tamper:
appended `from build123d import Cylinder  # TAMPER-PROBE` to
`src/mycad/core/geometry_types.py` (T1-owned; backup kept in /tmp, never
committed):

```
FAILED tests/test_layering.py::test_src_has_no_backend_imports - AssertionErr...
1 failed, 2 passed in 9.07s
```

Restored from backup (`git status --short src/mycad/core/` → empty, file
byte-identical to HEAD), re-ran:

```
3 passed in 8.71s
```

The whitelist now permits build123d/OCP/numpy imports ONLY in
`src/mycad/geom/`, `tests/geom/`, and `tests/helpers/step_roundtrip.py`
(T8 helper, does not exist yet — spec-exact wording).

## 4. Selector matrix ①–⑩ (test names ↔ plan rules)

`tests/geom/test_face_selectors.py`: matrix ① plane+Z rank0 largest flange
face; ② two-block stacked construction → ambiguous without rank (exactly 2
candidates, TopologyReferenceError, not a single cube); ③ rank=1 second
largest; ④ rank=99 → TopologyReferenceError with candidate count in reason;
⑤ cylinder+None → all 6 cylindrical faces; ⑥ cylinder ±Z undirected same
result; ⑦ cylinder +X on Z-axis → no-match; ⑧ plane axis omitted (None and
"") → ValidationError; ⑨ "" isomorphic to None; ⑩ equal-area lexicographic
tiebreak (smaller x,y,z wins). Plus: no-match count=0, empty kernel no-match,
directed plane matching, descriptor JSON echoed in failures, malformed
descriptor ValidationErrors, GeomType filtering.
`tests/geom/test_edge_selectors.py`: rule 6 — parent union dedup (4+4−1=7
edges), total order length-desc + midpoint-lex, parent-mismatch and
curve-filter-empty → TopologyReferenceError with command id + descriptor JSON.
`tests/geom/test_kernel_version.py`: gate passes for 0.11.1; monkeypatched
`importlib.metadata.version` → "9.9.9" (mismatch) and "0.11" (unparseable)
both raise GeomVersionError with actual AND expected in the message;
parametrized bad raw strings ("1.2.3.4", "abc", "0.11.x"); gate trips at
module import under monkeypatch and reloads cleanly after undo. The
implementation reads only `importlib.metadata.version`, never
`build123d.__version__`.

## 5. Finisher cleanup — basedpyright strict 28 → 0

| Path | Errors | Fix |
|---|---|---|
| `src/mycad/geom/query.py` | NameError (runtime) | add `from copy import deepcopy` |
| `src/mycad/geom/_b123_ops.py` | 7 | `Shape` not exported from `build123d` + unparameterized generic → retype helpers to `Part` / `Part \| Compound \| Wire` (matches boolean-op return types; placed primitives are `Part` subclasses) |
| `src/mycad/geom/selectors.py` | 6 | redundant `isinstance(x, Mapping)` on typed unions → else-branch; `list/tuple` narrowing to Unknown → `cast("Sequence[object]", ...)` + per-item isinstance + `cast("Mapping[str, object]", item)` |
| `tests/geom/test_edge_selectors.py` | 6 | `_edge_center(edge: object)` → `edge: Edge` + explicit `float()` on Vector.X/Y/Z |
| `tests/geom/test_face_selectors.py` | 1 | `Face.radius` is `float \| None` → assert-narrow with message |
| `tests/geom/test_kernel_version.py` | 7 | private-symbol import → public rename; untyped lambdas in `monkeypatch.setattr` → module-level `def _version_999(_name: str) -> str` fakes |

No `# type: ignore`, no `# pyright: ignore`, no `Any` escapes, no
`tests/typing/` created.

## 6. Scoped verification (all exit 0, 2026-10-04)

```
uv run ruff check src/mycad/geom tests/geom tests/test_layering.py
  -> All checks passed!
uv run ruff format --check src/mycad/geom tests/geom tests/test_layering.py
  -> 13 files already formatted
uv run basedpyright src/mycad/geom tests/geom tests/test_layering.py
  -> 0 errors, 0 warnings, 0 notes
uv run pytest tests/geom tests/test_layering.py -q
  -> 90 passed in 16.21s   (was: 3 failed, 87 passed on arrival)
uv run pytest tests/core tests/test_smoke.py tests/test_spdx.py -q
  -> 19 passed in 0.20s   (no regression outside scope)
```

## 7. Adversarial classes

- **malformed_input** — probed: rank=99, no-match, ambiguous, bad surface
  strings, bad curve, non-positive/non-finite tolerances, empty parent_faces,
  non-sequence parent_faces (all → ValidationError/TopologyReferenceError
  with command id + descriptor JSON).
- **flaky_tests** — probed: every volume/area expectation is a closed-form
  formula computed in the test with explicit tolerances (1e-6 mm³);
  tessellation counts only compared within a single construction.
- **misleading_success_output** — probed: volumes asserted against math
  formulas, not implementation echoes; version gate actually trips under
  monkeypatch; layering guard actually goes red under tamper; deepcopy
  re-mesh verified against fresh-part ground truth (§1).
- **stale_state** — probed: `reset()` → empty mass properties (§2);
  tessellation stale-cache hazard eliminated and proven (§1).
- **prompt_injection / cancel_resume / hung_commands / repeated_interruptions**
  — n/a this session (finisher pass, single-threaded, path-scoped commands
  only).
- **dirty_worktree** — integration-owned; no git operations performed.

## 8. Deviations

1. Version-gate callable renamed `_assert_b123d_version` → `assert_b123d_version`
   (public) so the test module can import it under basedpyright strict
   without `reportPrivateUsage`. The plan's "directly-testable callable"
   requirement is unchanged; the plan's own name was a non-binding example.
2. The plan's tessellation monotonicity wording ("chord halved → strictly
   more triangles") holds whenever the linear deflection binds; at 30°
   angular the 5→2.5 mm pair plateaus for physics reasons (§2). The test
   uses the 10→5 mm pair where the linear constraint binds, which is the
   honest reading of the spec.

No other deviations. Sibling scopes (`src/mycad/commands/**`,
`tests/commands/**`) untouched.
