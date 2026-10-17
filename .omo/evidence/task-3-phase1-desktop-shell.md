# task-3-phase1-desktop-shell — geom per-feature mesh extraction (ViewportPort)

Commit: `feat(geom): per-feature mesh extraction implementing ViewportPort`

## What landed
- `src/mycad/geom/kernel.py`
  - `BuildKernel` now implements `mycad.core.viewport_protocol.ViewportPort` structurally.
  - Snapshot semantics per plan todo 3: every successful `apply()` appends
    `("<command id>:<snapshot index>", deepcopy(post-execution Part))` to
    `self._snapshots`; `reset()` clears the list; undo/redo rebuild by full
    replay (`bus._rebuild`: `kernel.reset()` → replay history), so snapshots
    are naturally rebuilt in ordinal order — no cache/invalidation logic.
  - `viewport_data(linear_tolerance_mm=0.1, angular_tolerance_deg=15.0)`
    maps each snapshot through `geom/query.py::build_tessellation` (which
    deepcopies again — stale-triangulation annotation applies unchanged;
    `BRepMesh_IncrementalMesh` is not used, per plan). Defaulted optional
    parameters keep the zero-argument protocol call shape valid while
    letting callers request finer meshes. Empty doc → `()`.
- `tests/geom/test_viewport_snapshots.py` — 6 tests on the F3 flange
  sequence (`tests/geom/_geometry.py::build_flange`, 6 applies).

## Decision record (plan-text deltas, honest)
1. **feature_id numeric suffix = 0-based snapshot append index**, not a
   document ordinal plumbed through the Bus. The core `Kernel` protocol's
   `apply/reset` signatures are frozen (plan todo 2 "Must NOT"); the Bus
   has no per-record hook that carries `ExecutedCommand.ordinal` into
   `kernel.apply`. The index equals the feature_history ordinal whenever
   the history holds only geometry-affecting commands (metadata and
   named-group annotations never enter the replay sequence per
   `core/document.py`; all eight P0 builtins are geometry-affecting and
   call `apply` exactly once). A non-geometry plugin command in history
   produces no snapshot — accepted phase-1 delta, docstring-documented.
2. **Tolerances enter via defaulted keyword parameters** instead of a new
   protocol signature or module constants drilled elsewhere; defaults
   0.1 mm / 15 deg chosen for the OD80-class phase-1 preview scale.

## Gates (scoped)
- `uv run pytest tests/geom/test_viewport_snapshots.py tests/test_layering.py -q`
  → **12 passed** (6 new + layering invariant suite).
- `uv run ruff check` + `uv run ruff format --check` on both files → pass
  (2 files reformatted for line length, then re-verified).
- `uv run basedpyright src/mycad/geom/kernel.py` → 0 errors, 0 warnings, 0 notes.
