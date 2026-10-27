# In-canvas Dimensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace modal dimension entry with a complete persistent canvas workflow.
**Architecture:** Neutral optional dimension presentation data; shared solver semantics for projected and arc measurements; a focused UI controller owns picking, preview, placing, editing and toolbar commands. Existing draft undo and committed Bus paths remain authoritative.
**Tech Stack:** Python, PySide6, PlaneGCS, pytest-qt.
**Spec:** docs/superpowers/specs/2026-10-25-in-canvas-dimensions-design.md

## Global Constraints

- T1 layering, zero type suppression, SPDX headers, no new dependencies.
- Preserve existing working tree; do not commit unrelated changes.
- Saved old dimensions with omitted presentation fields retain behavior.
- Draft edits are local transactions; committed edits use CommandBus.

## Review Focus

- Hidden/locked layers and cross-sketch references: no accidental driving edits.
- Stale committed previews or document changes: no historical overwrite.
- Zoom/pan during placement and after reload: model-space anchors stay stable.
- Repeated dimensions, cancellation, failed solve: no partial history writes.
- Non-default work planes and existing downstream features: references/rebuild preserved.

### Task 1: Dimension data and solver semantics
**Files:** core/sketch_constraints.py, core/sketch.py, geom/sketch_constraints.py, builtin_commands/specs.py; tests/core/test_dimension_presentation.py, tests/geom/test_dimension_projection.py.
**Interfaces:** SketchConstraint gains optional position_mm, text_position_mm, axis and arc_length kind. Existing solve/update and serialization consume these fields.
- [x] Write failing serialization, invalid-input, projected measurement/driving and arc length tests; run to observe failure.
- [x] Implement optional fields, schema, measurement and solver integration; run scoped tests.

### Task 2: Canvas tools and direct editing
**Files:** ui/dimension_tools.py (new), ui/sketch_editor.py, ui/cad_icons.py, ui/icons/dim-*.svg; tests/ui/test_canvas_dimensions.py.
**Interfaces:** DimensionTools(editor) manages tool buttons, inline value input and pointer event filtering. Uses draft snapshot/apply and emits committed solve requests.
- [x] Write failing mouse tests for tool inventory, picking, placement/cancel, projected/arc/angle, continue/baseline/ordinate, drag and inline edit.
- [x] Implement controller, screen layouts from persisted anchors, hover preview, input and independent icons.
- [x] Run UI scope; verify pan/zoom, layer filters, cancel, undo.

### Task 3: Committed workflow and exchange
**Files:** ui/main_window.py, formats/providers/dxf_provider.py; tests/ui/test_canvas_dimensions.py, tests/formats/test_dxf_sketch_exchange.py.
**Interfaces:** Controller.committed_requested(original, constraint) submits preview+Bus update asynchronously with document/session validation. Drawing context updates after completion.
- [x] Write failing committed mouse/Bus/undo/reload and DXF presentation roundtrip tests.
- [x] Route dimension actions into canvas, integrate isolated previews and Bus, preserve coordinates in native exchange.
- [x] Run scoped checks, update README/UI design, final four gates once; fresh reviewer examines touched code and actual mouse workflow.

## Execution record

Native inline execution: user has authorized complete implementation; no further approval checkpoint. Existing codex/phase2-foundation checkout contains the prerequisite implementation and extensive uncommitted work; reuse it. Scope tests first, one final integration run. New optional fields are additive to the current unreleased schema implementation; omitted fields keep legacy behavior.


## Verification and review

- Neutral placement/projection/arc tests, DXF native measurement/roundtrip, all mouse acceptance paths implemented. First new failures observed before implementation.
- Independent reviewer reproduced baseline leakage, no-motion history, translated preview and driving-chain lifecycle defects; each fixed with a failing then passing mouse regression. Post-solve cancellation verified with a delayed worker and Escape; failed async previews have explicit retry.
- Final focused suites: UI 47 passed, neutral/geometry/DXF 36 passed. Strict type and lint/format correction scopes pass. Full integration logs are in `.omo/evidence/in-canvas-dimensions/`; intentional UI design doc change required regenerating its SHA256 baseline and scoped contract recheck (4 passed).
- Preserve the existing checkout and uncommitted work for user review; no merge, push or commit of unrelated prerequisites.
