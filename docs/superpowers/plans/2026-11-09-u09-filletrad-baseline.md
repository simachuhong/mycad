# U09 Drawing Fillet Baseline Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for sequential implementation. Check off completed steps and run only the listed focused checks until integration.

**Goal:** Give newly created 2D drawings a replayable `FILLETRAD` baseline of zero while preserving the baseline of existing files.

**Architecture:** Introduce an explicitly versioned archive baseline rather than overloading metadata or inserting an undoable initialization command. The document owns the immutable baseline; all kernel reset and replay paths, including isolated candidates, must initialize from the same document before replay. Existing v1–v6 files keep their legacy baseline of one. New 2D files use the new format; part files retain their current format.

**Tech Stack:** Python, CommandBus, archive validators, BuildKernel, PySide6 tests.

**Spec:** `.omo/evidence/ui-redesign/u09-human-acceptance.md`, FILLETRAD boundary; Autodesk FILLETRAD reference linked there.

## Global Constraints

- Preserve ADR-001 command-bus writes and the six audit fields; do not use an undoable bootstrap command or overload v1 metadata.
- Older archives, undo/redo, failed transactions and stale candidates must preserve their original baseline.
- A new archive version is a compatibility boundary: older MyCAD builds may reject newly saved 2D files.
- Do not change the default for parts or legacy files, including legacy files subsequently upgraded for other features.
- Run path-scoped checks; a full suite is reserved for final integration.

## Review Focus

- Empty new file, save/reopen, first edit, undo and redo all retain zero.
- Legacy v3/v4/v5/v6 files without an explicit radius retain one, including after upgrades and Save As.
- Isolated candidate replay, cancellation, rollback and kernel replacement use the owning document baseline.
- Referenced sketch snapshots and document copies preserve their baseline and reject malformed or incompatible versions atomically.
- Old schema versions reject new baseline fields; booleans, non-finite and negative values are invalid.

## Tasks

- [ ] Add focused tests for new and legacy baseline behavior, replay, candidate, Save As, document isolation and malformed archive input; reproduce failures.
- [ ] Add a v7 archive validator and an immutable typed baseline on Document; adapt serialization, copy and reference handling without changing legacy schemas.
- [ ] Propagate the baseline to every kernel initialization and replay path through a backend-neutral protocol, including detached candidates and reference loading.
- [ ] Update new 2D document construction and version ceilings; preserve old documents' archived baseline through upgrades.
- [ ] Run focused archive, bus, candidate, references, fillet UI and layering checks; update acceptance evidence with compatibility implications.

Progress: v7 validation, serialization, opening, document copies, candidate replay, kernel reset, direct and window reference upgrades, and new 2D document creation are implemented. The former strict xfail is removed. Targeted baseline/reference, dimension/fillet UI, old-archive projection and layering checks pass. Full integration and physical-device acceptance remain pending.
