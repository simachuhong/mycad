# U09 Polyline Curves Implementation Plan

**Goal:** Preserve a rounded polyline as one replayable entity with exact circular segments.

**Architecture:** Represent each directed segment with a DXF-compatible bulge, keeping straight legacy polylines byte-compatible. Generate a complete candidate before any edit. Add versioned serialization, exact geometry conversion, rendering, selection and supported edits before exposing trim-mode filleting; reject unsupported edits rather than silently straightening arcs.

**Tech Stack:** Python, neutral core DTOs, existing Command Bus and build123d adapter, PySide6, DXF provider.

**Spec:** `docs/design/2026-11-07-cross-sketch-fillet-remaining.md`.

## Constraints and review focus

- Preserve legacy command replay, archive versions, entity identities, layer and construction status.
- Reject invalid bulges, degenerate arcs, nonfinite values, overlapping corners and unsupported mutations atomically.
- Cover open/closed polylines, both orientations, concave vertices, undo/redo and save/reopen.
- Respect existing constraints, locked layers, mixed draft/saved edits and source-revision changes.
- Keep core free of CAD/Qt backends and DXF import/export lossless.

## Tasks

- [x] Implement and test pure corner-to-bulge candidate generation and segment-to-arc conversion.
- [x] Add a versioned DTO/schema for curved polylines, with legacy serialization unchanged and strict old-version rejection.
- [ ] Finish exact kernel profiles, viewport geometry, snaps, hit testing and DXF round trips; gate unsupported operations. Exact profile construction, canvas selection, viewport snaps and DXF exchange are implemented; additional edit and constraint paths need coverage.
- [ ] Finish trim-mode P transactions, constraint safeguards, undo/redo and persistence. Draft, saved and mixed paths support straight, line/arc and arc/arc corners and replacement/removal of tangent line/arc/line fillets; edge cases and reference-software behavior remain.
- [ ] Verify scoped suites and compare observable workflows with the supplied reference recording; document unobserved cases.
