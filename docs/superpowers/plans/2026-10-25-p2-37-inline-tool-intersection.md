# P2-37 inline-tool intersection implementation plan

> **For agentic workers:** Follow TDD. Keep the change bounded to the current model intersected with one inline primitive tool; do not create persistent body references.

**Goal:** Release `modify.boolean_intersect@1` with a deterministic geometry, CLI, and explicit UI preview/confirm workflow.

**Architecture:** Keep schema, Bus, archive and CLI semantics in core/application layers; implement BREP intersection only in `mycad.geom`; reuse the existing tool-placement/confirmation interaction in UI. Every document write goes through CommandBus.

**Reference:** `docs/superpowers/specs/2026-10-25-p2-37-inline-tool-intersection.md`; release contract is recorded in ADR-003 before command implementation.

## Tasks

- [x] Add failing schema, command-ID, affected-object, alias, geometry and replay tests for the explicit intersection slice; targeted run confirmed the missing-command/kernel/UI failures.
- [x] Record the `modify.boolean_intersect@1` contract in ADR-003 and update its released-ID/audit locks.
- [x] Implement the geometry operation with valid nonempty-result checks and replay-safe error behavior.
- [x] Connect the command to the shared tool-placement bar, command palette/toolbar, preview and confirmation path.
- [x] Add Bus save/reopen/undo/redo and CLI grammar coverage; prove failures do not mutate history.
- [x] Run scoped tests, Ruff, formatting, basedpyright, and diff checks; record evidence and remaining P2-37 limits.
