# Driving Dimensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make new in-canvas dimensions driving by default, with reliable direction and editable fixed-end policies.
**Architecture:** Add optional neutral anchor metadata, apply temporary solver gauges only to the active edit, keep frozen Bus replay and original constraints. Reuse inline controls and add canvas diagnostics.
**Tech Stack:** Python, PySide6, PlaneGCS.
**Spec:** docs/superpowers/specs/2026-10-26-driving-dimensions-design.md

## Global Constraints
- Preserve dirty prerequisites, T1 layering, zero type suppression, SPDX, Bus-only writes.
- Native inline execution already authorized; no further approval checkpoint or unrelated commit.
- Omitted anchor_mode means auto; archived solved coordinates never re-solve.

## Review Focus
- Reversed lines and signed ordinate values preserve intended direction.
- Existing fixed/locked geometry takes precedence in auto; explicit conflicts cannot partially apply.
- Centered rectangle edits maintain midpoint and orthogonal shape.
- Temporary gauges do not falsely report full constraint or persist extra relations.
- Reference conversion, inline cancellation and stale asynchronous previews preserve history.

### Task 1: Metadata and signed projections
Files: core/sketch_constraints.py, builtin_commands/specs.py, geom/sketch_constraints.py; tests/core/test_dimension_anchors.py, tests/geom/test_dimension_driving.py.
- [x] Add failing roundtrip/legacy validation and directed horizontal/vertical/ordinate tests.
- [x] Add optional anchor_mode enum and fix PlaneGCS difference order; verify scoped checks.

### Task 2: Predictable fixed ends
Files: geom/sketch_constraints.py; tests/geom/test_dimension_driving.py.
- [x] Add failing fixed start/end/centered, connected/locked, rectangle/circle and true-DOF tests.
- [x] Add transient edit gauges, independent anchor residual validation and original-system DOF; verify solving and archive/undo regression.

### Task 3: Inline defaults, anchor controls and diagnostics
Files: ui/dimension_tools.py, ui/sketch_editor.py; tests/ui/test_driving_dimensions.py, existing reference fixtures.
- [x] Add failing default-driving, reference switch, inline anchoring/convert/cancel/conflict and committed Bus tests.
- [x] Implement default driving, anchor selector and canvas diagnostics while preserving DIM/style/identity.
- [x] Update tests that intentionally exercise reference placement to select reference explicitly; scoped UI checks.

### Task 4: Review and integration
Files: README.md, docs/UI设计初稿.md, doc baseline fixture, .omo/evidence/driving-dimensions/.
- [x] Fresh independent read-only review; fix concrete findings with regression tests.
- [x] Update docs/hash, run final full four gates once and scoped corrections as needed; save evidence/screenshots.
