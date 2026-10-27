# DIM Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Default dimensions to DIM and provide independent document-wide layer on/off, freeze/thaw and lock state.
**Architecture:** Optional neutral annotation layer and frozen layer attributes; replayable drawing.layers.set applies shared layer properties to all sketches and retains the default dimension layer. A non-modal layer table and canvas filters use the same state, without changing solver participation.
**Tech Stack:** Python, PySide6, PlaneGCS, ezdxf.
**Spec:** docs/superpowers/specs/2026-10-25-dim-layers-design.md

## Global Constraints
- Preserve current uncommitted prerequisite work and current codex checkout; no unrelated commits.
- T1 layering, zero type suppression, SPDX; only Bus mutates document history.
- Omitted annotation layer retains legacy geometry-layer inheritance; omitted frozen means false.
- Frozen/off states never remove driving constraints or geometric truth.

## Review Focus
- Different sketch layer tables must share one document state, including when all layers are hidden.
- Hidden geometry must not hide independent DIM annotations; hidden DIM must not change geometry.
- Frozen current layer is rejected; frozen and off flags remain independent through undo and DXF.
- Draft geometry undo must not restore obsolete document layer properties.
- Consumer regeneration and failed transactions must retain layer state and dimension assignments.

### Task 1: Neutral layer metadata
**Files:** core/sketch_layers.py, core/sketch_constraints.py, core/sketch.py, builtin_commands/specs.py; tests/core/test_dim_layers.py.
**Interfaces:** SketchLayer.frozen / displayed, SketchConstraint.layer_name, DEFAULT_DIM_LAYER and layer table helpers; schema accepts additive fields.
- [x] Write tests for frozen/off independence, legacy parsing, DIM creation and annotation layer validation; observe failures.
- [x] Implement optional fields and validation preserving old serialization; run scoped tests.

### Task 2: Replayable global layers and exchange
**Files:** geom/kernel.py, builtin_commands/specs.py, formats/providers/dxf_provider.py; tests/geom/test_drawing_layers.py, tests/formats/test_dim_layer_exchange.py.
**Interfaces:** kernel.drawing_layers, dimension_layer; drawing.layers.set(layers, dimension_layer, assignments) synchronizes all committed sketches; no solver changes.
- [x] Write Bus/undo/reopen, cross-sketch and native DXF state/annotation tests; observe failures.
- [x] Implement kernel state, atomic validation/replay, frozen display exclusion and DXF freeze/layer fidelity; verify scopes.

### Task 3: Canvas semantics and dimension target
**Files:** ui/sketch_editor.py, ui/dimension_tools.py, ui/layer_panel.py (new UI helper); tests/ui/test_dim_layers.py.
**Interfaces:** editor.set_document_layers(table, dimension_layer), layer_change_requested; canvas independent annotation layer filtering and styling, frozen selection/snap/extents rules; target layer combo and batch migration.
- [x] Write mouse tests for DIM default, independent visibility, frozen/current guard, style and annotation lock, legacy batch migration.
- [x] Implement filters, target preference, non-modal layer table and draft state synchronization; run UI scopes.

### Task 4: Main-window integration and final verification
**Files:** ui/main_window.py, README.md, docs/UI设计初稿.md, baseline hash fixture.
**Interfaces:** asynchronous global layer Bus submission, initial/undo/redo synchronization and local-undo layer barrier.
- [x] Write committed+draft layer UI/Bus/save/reopen tests and verify failures.
- [x] Integrate without discarding pending draft geometry; verify targeted checks, fresh independent review, then one final full four-gate run.
- [x] Save UI screenshots and validation evidence; leave checkout for user review.

## Execution
User approved whole scope. Continue native inline execution without another approval checkpoint. Reuse existing checkout because prerequisites are uncommitted here. Progress is recorded in .omo/start-work/ledger.jsonl; failures use scoped rechecks.
