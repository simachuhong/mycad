# Independent review and visual QA

A fresh read-only reviewer reproduced two actionable UI issues; backend sign, transient gauges, DOF and frozen replay were inspected with no further concrete backend issue reproduced.

1. P1: anchor_combo was constructed but omitted from the command-row layout. A new visibility/layout assertion failed; it is now a visible child in the command bar.
2. P2: confirming a new dimension left an inactive inline input visible. New confirmation assertions failed; successful commits now hide/reparent that input and return focus to the canvas while retaining continuous dimension mode. The focus assertion processes the Qt activation event before checking focus.

Additional visual QA found dimension lines and dependent reference values still using accepted geometry during preview. A failing regression now verifies that displayed dimension geometry and reference values use the solved candidate while accepted entities/constraints remain unchanged, and Esc restores measurements. Projected preview annotation positions are transformed with their source sketch frame.

Snapshots show a rectangle changing from width 80 to 120 with its first corner held, visible driving/anchor controls and true persistent DOF; an explicit conflicting fixed-start edit highlights the original rectangle and dimensional annotation in red and leaves the geometry unchanged.

No independent-review agent modified repository files. Existing uncommitted prerequisites were preserved.
