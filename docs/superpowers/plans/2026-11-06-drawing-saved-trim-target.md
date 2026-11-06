# Saved Drawing Trim Targets Implementation Plan

**Goal:** Allow trim, extend and split on saved independent 2D entities without bypassing replay or losing draft work.

**Architecture:** Resolve target and boundaries against the visible current workplane projection, calculate exact frozen geometry using existing sketch edit algorithms, then validate revisions in an isolated replay candidate. Saved-only changes use atomic revisions; operations involving unsaved draft boundaries use provisional mixed history to preserve ordering and discard semantics. Preserve unchanged entities, layers and constraints; reject stale, locked, ambiguous or non-replayable changes without partial results.

- [x] Add red UI tests for saved targets, geometry identity, undo/redo and persistence with saved-only boundaries.
- [x] Implement saved-only click editing with valid previews and candidate commit; maintain correct workplane conversion.
- [ ] Add and implement mixed draft/saved boundary and target cases, cancellation, drag and sequential history without prematurely committing a draft.
- Mixed click editing, sequential history and cancellation-safe staging are covered. Multi-target drag now uses atomic candidate replay; broader geometry and failure combinations remain to verify.
- [ ] Verify constrained, linked, locked, hidden, duplicate and stale paths; run scoped UI, replay and geometry regressions and update the audit.
