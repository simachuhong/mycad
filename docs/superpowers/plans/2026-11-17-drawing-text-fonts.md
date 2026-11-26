# Drawing Text and Fonts Implementation Plan

> **For agentic workers:** Use focused parallel agents only for disjoint backend and Qt-service files; parent integrates UI and exchange. Track completion below and never run full suites.

**Goal:** Implement editable independent 2D TEXT/MTEXT and document STYLE with persistent font resources and DXF exchange, ready for focused unit testing.
**Architecture:** Backend-neutral immutable records and Bus commands; Qt resource/layout services; existing QWidget canvas integration; native ezdxf entities.
**Tech Stack:** Python, PySide6, ezdxf 1.4.4, existing MyCAD Bus/history.
**Spec:** docs/superpowers/specs/2026-11-17-drawing-text-fonts-design.md

## Global Constraints

- Reuse current clean codex/phase2-foundation checkout; do not discard unrelated work or create/commit a new worktree.
- User authorizes implementation now; no additional design approval is needed.
- All model writes through Bus; no Qt in core; no type suppressions; SPDX headers.
- Only incremental scoped verification; no full test suite or repeated unaffected tests.
- User delivery boundary is implementation ready for unit testing; minimal developer tests are permitted to prove new integration contracts, not final acceptance.

## Review Focus

- Font unavailable after reopen: preserve requested style, render fallback and report missing glyphs.
- Text-only document: export and import without requiring sketch geometry.
- Chinese IME and Esc: no preedit history, cancel preserves original, Ctrl+Enter commits once.
- Style ID/name collisions: paste/import must not restyle existing text.
- Native DXF edits: import native content/placement instead of stale custom metadata.

## Tasks

- [x] 1. Backend: core/drawing_text.py models and transformations; builtin_commands/text_specs.py plus registration; geom/kernel.py state lifecycle and handlers; Bus/document kind gates. Tests tests/core/test_drawing_text.py and tests/app/test_drawing_text.py for mapping, validation, atomic rejection, undo/redo, persistence, layer/style references.
- [x] 2. Qt services: ui/font_manager.py and ui/text_layout.py; scoped tests tests/ui/test_text_layout.py for baseline, wrapping, alignment, width scaling and missing glyphs; font resource staging/rollback.
- [x] 3. Exchange: formats/text_exchange.py helpers plus dxf_provider integration; texts/text_styles added to import record and pure-text export; tests/formats/test_dxf_text_exchange.py for TEXT/MTEXT native fields and escaping.
- [x] 4. UI: ui/drawing_text_tools.py controller, property/style/font UI; SketchCanvas event/paint and selection integration; Drawing2DCommandBar TEXT/MTEXT/STYLE entry; MainWindow guarded Bus bridge and lifecycle (existing scalar settings path; mixed geometry edits use the existing worker); clipboard and supported transforms; focused UI integration checks.
- [x] 5. Audit: inspect diff against spec, run changed-path lint/format/type and only directly relevant new/affected tests; update README, record readiness and remaining formal unit-test matrix.

Each task: write its behavior tests first; observe targeted failure; implement; run only that task's scoped checks. Record evidence below as work proceeds. No automatic commits or publishing.

## Progress

- Planning: current HEAD 8b5c113, clean tree. Previous assessment is authoritative intent; fresh source inspection reconfirmed native Bus.execute and QWidget SketchCanvas interfaces.
- Task 2: implemented persistent hash-deduplicated TTF/OTF/TTC registration, reload and rollback, family/file lookup and visible substitution reporting; native Qt text shaping with cap-height millimetres, wrapping, width scaling, baseline/box alignment and actual glyph ink bounds. Developer checks: initial collection red until backend records landed; then 6 passed / 1 failed for italic overhang, fixed shaped ink bounds and reran only the affected layout file (4 passed). The 3 font resource tests passed in the first run and were not repeated. Owned-path ruff check and format check passed; basedpyright reported 0 errors, 0 warnings. No full suite was run.
- Import/clipboard integration: commit_new_sketch accepts imported_texts/imported_text_styles/imported_rasters and stages layer preparation, optional geometry, text/style and image batches in one replay operation. Added pure core style collision reconciliation, text/image ID remapping, existing layer-property preservation, text-only import without empty geometry and incoming dimension-style retention. Scoped developer evidence: first 3 import cases passed; the added text-only dimension-style case passed after using the current clipboard preparation schema; one directly affected pre-existing dimension-style regeneration case passed once. The added mixed text/image clipboard case passed with and without geometry (2 cases); unaffected passing tests were not repeated. App/helper/import-test lint, format and strict typing passed. No full suite was run.

- Task 3: Added `formats/text_exchange.py`, native TEXT/MTEXT/STYLE exchange, deterministic native-name style IDs, text-only documents, font filename/family, millimetre scaling, literal escaping and native-edit authority. Scoped evidence: initial new exchange checks 9 passed; additional native/literal/unsupported-format checks 3 passed; Unicode TEXT check red→green (1 passed); affected TEXT checks after Unicode escaping 8 passed. Existing one-sketch provider integration 1 passed. Owned three-file ruff lint, format and basedpyright pass. No full suite. MTEXT baseline alignment converts to native bottom attachment with a report warning; unsupported rich formatting is flattened with warnings.

- Task 1 backend: immutable text/style records, pure transforms, five replayable Bus commands, candidate lifecycle and locked/frozen layer protection implemented. Archive floor 4 uses existing sketch document kinds and JSON command history; no archive payload change. Developer checks: core tests 8 passed; app text lifecycle/gates tests 5 passed; additional custom-layer sketch regeneration regression 1 passed (plus 8 core tests after helper refactor). Changed-path ruff check/format and basedpyright passed (8 paths, 0 type errors). Initial red confirmed missing models/commands; regression red confirmed custom layer missing during geometry regeneration, then green after preserving final neutral text state. No full test suite run.

- Task 4/5: completed UI controller, text properties with dirty-field multiselection, font/style/resource dialogs, command/menu/toolbar entry, same-layout canvas painting/picking and mixed clipboard/import integration. Fixed independent-document factory routing, pending-text save/finish/undo/redo guards and shared mixed geometry undo. New controller/clipboard checks passed incrementally, including separate red/green regressions for mixed move, dimension-style paste and multi-property preservation. Final direct existing regressions: catalog/CLI 6 passed, clipboard/ordinary text shortcuts 3 passed, document lifecycle + draft scale 2 passed, architecture layering 6 passed. All 31 changed Python files pass lint and format; strict typing passed per changed group. Normal canvas image inspected for Chinese, symbols, multiline leading, rotation and selection. Final two Important findings rechecked by the independent reviewer as resolved.
- Delivery boundary: implementation is ready for formal scoped unit testing; no whole-project suite, native Windows run or external CAD acceptance was performed. Detailed requirement/evidence matrix, formal test entry files and declared compatibility boundaries: `.omo/evidence/drawing-text-fonts/readiness.md`. No commits, pushes or dependency changes.
