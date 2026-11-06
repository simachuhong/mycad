# Atomic Mixed Drag Trim Implementation Plan

**Goal:** Support dragging across multiple saved and draft targets without applying only part of the gesture.

**Architecture:** Capture original draft, constraints, selection and projected saved geometry at gesture start. Calculate provisional edits against one evolving projection and keep a per-target event log mapping each generated fragment to its owning sketch. No document command executes until release. Resolve all saved edits to frozen local sketch revisions and validate them together in an isolated replay candidate; when a draft is involved, stage draft and saved changes in the existing mixed history. Cancel, stale state, locked/ambiguous targets, constraint or replay failure restore the full pre-gesture state. Keep candidate rendering, snap data and selection synchronized.

- [x] Add failing tests for multiple saved targets, multiple intervals of one target and mixed draft/saved targets, including one-step undo, cancel and failure atomicity.
- [x] Implement provisional saved geometry and target ownership tracking for the drag, without publishing commands during the gesture.
- [x] Commit saved-only revisions atomically or stage a mixed draft/saved timeline; preserve all draft constraints or explicitly reject unsupported changes.
- [ ] Verify locked/hidden sources, topology type changes, stale revisions, workplane mapping, save/reopen and existing drag regressions; update audit.
