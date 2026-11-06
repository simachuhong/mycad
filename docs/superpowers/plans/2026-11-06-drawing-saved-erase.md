# Saved Drawing Erase Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and track the steps below.

**Goal:** Let Delete remove selected committed 2D geometry, including mixed draft selections, with consistent replay, undo, and dependent-constraint handling.

**Architecture:** Reuse `sketch.revise` / `drawing.sketch.revise` and the existing isolated replay candidate. When draft and committed geometry are mixed, extend the existing provisional mixed timeline rather than committing part of the selection. Remove relations referencing deleted entities, reject locked or hidden layers, and preserve the entire selection on failure. Never directly mutate the document or bypass dependency validation.

**Tech Stack:** Python, PySide6, Command Bus, pytest-qt.

## Tasks

- [ ] Establish with real replay tests whether revisions may leave an empty sketch, how downstream dependencies fail, and how existing constraints are removed; retain explicit failure where a dependency cannot be resolved.
- Empty-sketch revisions have been confirmed through save/reopen and undo/redo. Downstream dependency and constraint cases remain open.
- [ ] Add a failing real-window Delete test for a saved selection, then implement candidate validation, asynchronous commit, and undo/redo without changing unrelated objects.
- Single saved-object Delete, undo/redo and GUI save/reopen are implemented and tested. Deletion across two committed sketches is one undo step; duplicate entity identities are rejected.
- [ ] Add tests for draft/saved mixed selection, provisional undo/redo and final save/reopen; implement atomic provisional deletion using the existing timeline, preserving selection and draft on rejection.
- Mixed deletion, empty-draft lifecycle handling, provisional undo/redo and save/reopen are implemented and tested; additional cross-sketch and failure paths remain.
- [ ] Cover dependent user and inferred constraints, locked and hidden layers, stale revisions, linked sketches, multiple source sketches, and deletion of every entity in a sketch; reject unsafe cases visibly rather than partially applying them.
- [x] Add command-line ERASE/E for preselection and command-first selection, including Enter/right-click completion, Esc cancellation and command repeat; route execution through the same Delete path and guards.
- [ ] Run relevant UI, replay, constraint and persistence tests plus scoped lint, format and type checks; update U09 evidence and audit with exact supported scope and archive-version behavior.
