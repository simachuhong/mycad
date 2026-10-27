# Drafting interaction repairs Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Repair interactive rotation/mirroring, add regular polygons, and offer hideable dot grids.

**Architecture:** Extend the existing SketchCanvas gesture lifecycle and reuse core sketch transformations. Regular polygons are closed PolylineEntity objects, preserving existing archive/export/undo paths. Grid visibility is a display preference independent of snapping.

**Tech Stack:** Python, PySide6, pyqtgraph, pytest-qt.

**Spec:** User's 2026-10-26 request and explicit approval: “按建议直接修补”. Default rotation is center + angle/direction; optional reference rotation uses center/from/to; mirror uses an arbitrary two-point axis and retains sources by default. Polygon supports side count and inscribed/circumscribed radius. Grid uses dots and an independent F7 toggle.

## Global Constraints

- Preserve existing uncommitted work in this checkout; no bulk staging or commits.
- Preserve CommandBus/document boundaries, zero type suppressions, locked-layer and constraint guards.
- Existing numeric transform controls remain available as explicit actions.
- Run scoped gates during development, full gates once at final integration.

## Review Focus

- Command-first selection and preselection must both work.
- Preview/cancel must not mutate geometry, constraints, or undo history.
- Degenerate axes/radii and constrained or locked objects must remain safe.
- Polygon geometry must remain exportable and replayable as a closed polyline.
- Hidden grids must not disable snapping or reappear when continuing a drawing.

### Task 1: Interactive transforms

- [x] Add failing tests in tests/ui/test_drafting_interaction_repairs.py for arbitrary-center angle rotation, reference rotation, diagonal mirror with keep/delete source, cancellation, command-first selection, undo/redo, and constraints.
- [x] Run new tests and confirm missing-interaction failures.
- [x] Extend SketchCanvas.begin_transform, candidate/preview/commit and numeric angle entry in src/mycad/ui/sketch_editor.py. Wire toolbar actions, reference mode and keep-source controls; retain explicit numeric rotation.
- [x] Verify the new tests plus tests/ui/test_drafting_mouse_transforms.py and tests/ui/test_sketch_editor.py.

### Task 2: Polygons

- [x] Add failing tests for regular polygon side count, inscribed/circumscribed radius, preview cancellation, layer properties and undo/redo.
- [x] Add polygon options and center/radius placement through SketchCanvas._make_entity; use closed PolylineEntity. Add draw-polygon.svg and icon registration.
- [x] Run polygon and existing drawing tests.

### Task 3: Dot grids and final integration

- [x] Add failing image/interaction tests for isolated grid dots, F7 visibility, independent snapping, workspace continuation; add 3D XY dot-grid coverage.
- [x] Add grid visibility to SketchCanvas and dialog; draw point intersections instead of grid lines. Replace viewport XY GLGridItem with GLScatterPlotItem while preserving its visibility action.
- [x] Update README with interaction instructions.
- [x] Run scoped lint/format/type/tests, then full four gates once. Review task-only diffs against saved pre-change copies and record results in .omo/start-work/ledger.jsonl.
