# Sphere Primitive Implementation Plan

**Goal:** Deliver the approved sphere command and desktop workflow.

**Architecture:** Extend the existing primitive/Bus/replay paths and shared scene positioning. Sphere has no planar source roles; exact center anchors must come from geometry.

**Tech Stack:** Python, build123d/OCCT, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-sphere-primitive-design.md`

## Global Constraints

Preserve existing uncommitted work, layering, schema version strategy, transaction and replay semantics. No unconditional archive migration. Test incrementally and run the four full gates once on final integration.

## Tasks

1. Add failing command, primitive, boolean, lineage and replay tests. Register sphere and implement geometry, source tracking and strict validation; verify scoped tests.
2. Add failing exact-center anchor tests covering visibility and post-boolean behavior. Expose only a defensible analytic sphere center through the existing scene port; verify scoped tests.
3. Add failing Qt workflow tests. Integrate sphere into the existing command bar, candidate previews, XYZ placement, and shared positioning; verify cancel, failure, stale previews and confirmation.
4. Verify persistence, undo/redo, export, history editing, integration and the four final gates; document actual results and remaining manual acceptance.
