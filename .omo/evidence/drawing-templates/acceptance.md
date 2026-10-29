# Drawing templates verification

2026-10-28: approved built-in GB/ISO + DXF library scope.

- Core templates: 22 new tests (all A0–A4 orientations, embedded replay, undo/redo).
- DXF import/library: 8 tests including units, blocks, attribute tags, rotated/scaled nested blocks, invalid file, geometry/text out of paper, missing units, unsupported entities and broken library file.
- UI: 9 tests covering selection/fields/undo, embedded custom size, shared PDF/DXF, import preview/mapping/cancel.
- Final scoped integration: 77 passed in 36.83s.
- Strict typing for changed modules and added tests: 0 errors.
- PDF from real export was independently rendered using Poppler; gb-preview.png and iso-preview.png inspected for glyphs, title grid, rotation and dimensions.
- Standard registry sources verified; the general title grid is MyCAD-authored. Full formal standards compliance and commercial CAD visual compatibility are not claimed.

Implementation decisions: reuse current codex branch, keep v1 commands intact, use v2 sheet commands for template snapshots; user library is filesystem data outside the document bus, applying to a drawing always uses the bus. DXF import rejects unsupported content instead of silently dropping it.

Independent review: 4 P2 findings reproduced and corrected (pending title fields, constant ATTDEF, classic POLYLINE width, multiline alignment); latest format/UI suite: 15 passed in 16.48s. Canvas/GUI workbench.png visually inspected. Full integration finished; see results below. Added library-entry integration and both GB/ISO PDF output coverage.

Performance spot check: 20 GB template canvas redraws in 0.197 s on this host.


## Final verification and baseline attribution

- Full ruff check and format check: passed; full basedpyright: 0 errors. Subsequent edited paths were checked again successfully.
- Final scoped integration: **77 passed** (36.83 s), including 39 template tests and 38 related regression/layering tests.
- One full pytest run: **2147 passed, 16 failed** (1406.02 s). This run had already imported the pre-fix multiline rendering code when the isolated review fix was applied.
- **13 pre-existing failures** were reproduced against an untouched `git archive HEAD` snapshot (13/13 failed with the same stale command/DTO/palette expectations). No unrelated baseline assertions were changed.
- The two multiline alignment cases and the 3-second projection timing case were rerun against final code: **3 passed** (21.24 s). The timing case exceeded its target during the concurrent full run (4.389 s); it passed on recheck. Full suite success is not claimed.
- Evidence: full-tests.log, baseline-failures.log, scoped-tests.log, final-recheck.log, full-types.log; workbench.png, gb-preview.png, iso-preview.png.
- No new dependencies, no schema-v1 changes, no changes to user LogoV1.png or assets/.
