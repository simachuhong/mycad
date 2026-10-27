# Nonmodal Modeling Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the confirmed non-obstructing, preview-first fillet workflow to every built-in modeling command.

**Architecture:** Add one reusable top-area command bar that renders operation-specific controls and serializes their values to existing command schemas. MainWindow owns selection, draft validation, preview generations, and explicit commits; GLViewport continues to render the candidate while resolving picks against the committed source snapshot.

**Tech Stack:** Python 3.12, PySide6, pytest-qt, existing PlanDraftController, SerializedExecutionUnit, preview_command, and CommandBus.

**Spec:** `docs/superpowers/specs/2026-10-25-nonmodal-modeling-workflows.md`

## Global Constraints

- Preserve T1 layering and keep PySide6 imports within `src/mycad/ui/`.
- Keep every confirmed write on the existing Plan/CommandBus path; previews use isolated scratch geometry.
- Preserve `.mc.json` v1 and the existing backend-neutral selector schemas.
- Keep the model visible and the camera stable through every command preview.
- Keep the existing continuous fillet command behavior working.

## Review Focus

- Rapid field edits followed by a slow preview must never display or enable confirmation for stale geometry.
- Changing a selected face while a candidate is visible must resolve against the committed model and preserve the new face selection.
- Switching profile/tool kind must serialize only fields valid for that schema branch.
- Cancel and document replacement during pending preview must discard the candidate without changing history.
- Narrow viewports must keep the command bar compact and fully outside the GL viewport.

---

### Task 1: Shared operation-specific command bar

**Files:**
- Create: `src/mycad/ui/modeling_toolbar.py`
- Test: `tests/ui/test_modeling_toolbar.py`

**Interfaces:**
- Produces `ModelingCommandBar.configure(command_id, selection_prompt)`, `values()`, `set_placement_point(point)`, `set_selection_status(message)`, and `set_preview_valid(valid)`.
- Emits `parameters_changed`, `commit_requested`, and `cancel_requested`.

- [x] Write failing tests for all seven non-fillet built-ins’ schema-shaped values, type-switch field filtering, and command-bar sizing.
- [x] Run the focused test and confirm it fails because the shared bar is absent.
- [x] Implement compact command-specific fields in the shared bar; keep values schema-shaped and do not add unsupported hole point placement.
- [x] Run the focused test and confirm it passes.

### Task 2: Selection, scratch preview, and explicit commit flow

**Files:**
- Modify: `src/mycad/ui/main_window.py`
- Modify: `src/mycad/ui/viewport.py`
- Test: `tests/ui/test_modeling_interaction.py`

**Interfaces:**
- MainWindow maps workplane picks into `center`, `profile.center`, or `tool.center`; maps one-face picks into `target_face` or `base_hole.target_face`.
- Candidate rendering remains transient. Active modeling picks resolve against `_current_snapshot()` even while the candidate is visible.
- Only current valid previews enable the command-bar commit action. One-shot modeling commands exit after success; fillet keeps its current repeat-group behavior.

- [x] Add UI tests for command-bar placement outside the viewport, source-model repicking over a candidate, automatic preview, explicit commit, and cancel without history writes.
- [x] Run the focused tests; the fillet compatibility case exposed and verified a candidate-pick regression before its guard was corrected.
- [x] Connect the shared bar to command draft parameters, selection routing, preview debounce/generation guards, and plan completion/failure handling.
- [x] Run the focused UI test files and confirm the workflow passes.

### Task 3: Validate the full interaction surface and launch for manual review

**Files:**
- Modify: `tests/ui/test_modeling_toolbar.py`
- Modify: `tests/ui/test_modeling_interaction.py`
- Modify: `docs/superpowers/specs/2026-10-25-nonmodal-modeling-workflows.md`

- [x] Check ruff, formatting, basedpyright, and the scoped UI tests.
- [x] Run the GUI against the updated workspace and leave it open for manual testing.
- [x] Record the verification result and any known capability limits in `.omo/start-work/ledger.jsonl`.

