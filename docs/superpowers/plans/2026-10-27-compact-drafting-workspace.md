# Compact Drafting Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline.

**Goal:** Maximize the 2D canvas while keeping navigation, command inputs and shared consoles accessible.
**Architecture:** One right drafting dock, compact top finish controls, shared collapsible bottom console in MainWindow. Signal-based status forwarding preserves inline operations.
**Tech Stack:** Python / PySide6 / pytest-qt.
**Spec:** docs/superpowers/specs/2026-10-27-compact-drafting-workspace-design.md

## Global Constraints
Preserve dirty prerequisite work, Bus-only writes, no type suppressions or backend imports in UI. No automatic restart. Use scoped verification. No mixed-tree commits.

## Review Focus
- Old saved navigation dock state must not reserve left canvas space.
- Floating right dock and console must not steal focus from dimension input.
- Repeated sketch commits and workspace switches must not duplicate status logs or lose console text.
- Long prompts and narrow windows must not force window growth.
- CLI document replacement must respect an active unsubmitted draft.

### Task 1: Consolidate drafting controls
**Files:** sketch_editor.py; tests/ui/test_drafting_panels.py; test_polygon_grid.py.
**Interfaces:** navigator remains read-only; parameter_tabs keeps named page references; message label exposes text_changed.
- [x] Add failing tests for one right dock, moved controls, full-height canvas and old layout migration. Expected: FAIL before removal of left dock.
- [x] Move controls and preserve lifecycle and selection tests. Expected: scoped panel/grid tests PASS.

### Task 2: Shared compact console
**Files:** new ui/workspace_console.py; main_window.py; tests/ui/test_workspace_console.py.
**Interfaces:** MessageLabel.text_changed(str), WorkspaceConsole.set_expanded(bool), information.append_message(str); shared CLI/plan unchanged.
- [x] Add failing integration tests for collapsed 2D console, expansion, prompt history and shared session. Expected: FAIL before new console.
- [x] Implement Information / CLI / AI / Plans; offline AI accurately identified pending user choice. Expected: targeted tests PASS.

### Task 3: Verification and delivery
- [x] Scoped lint/format/types and UI interaction suites; render real Qt screenshot; fresh review against task-entry snapshots; fix Important/Critical findings and verify.
- [x] Update README and evidence; leave running user app untouched.
