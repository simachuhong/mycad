# Independent review and corrections

Read-only reviewer reproduced three issues. All received regression tests that failed before repair and passed after repair.

- **P1, dimension regeneration:** replaying an obsolete global layer table against final annotation assignments rejected a valid dimension update. Consumer rebuild now retains the presentation history slot and uses final layer state.
- **P1, mixed undo:** identical geometry signatures lost the ordering of multiple global layer commands and local draft edits. Unique draft history positions and per-command boundaries now preserve undo/redo ordering. Keyboard, toolbar and menu route through the shared coordinator.
- **P2, modeless manager:** changing the current layer in the editor did not update the open layer panel. Current-layer changes and local-history restoration now synchronize the panel; rejected freeze operations reset its display.

Additional visual QA found annotation extents omitted from fit-view. Unfrozen dimensions now contribute extents even when their layer is off, and frozen dimensions do not. Native DXF assertions check raw DIMENSION layer ownership and independent off/frozen/locked flags.

Scoped results: review regressions/integration **13 passed**; subsequent core/geometry/UI/native-DXF **19 passed**; canvas/solver/exchange regression **124 passed**; extents/catalog integration **17 passed**. See final logs for subsequent checks.

Further history branch validation found that a new global command must discard abandoned local redo. A failing regression demonstrated a redo referencing a removed layer; the new global command now clears this future branch. The final layer UI suite passes **11 tests**, including native command-palette routing to the modeless manager. Catalog correction run: 27 passed, one remaining plugin-category expectation updated and separately passed. Full validation logs retain initial failures for transparency.
