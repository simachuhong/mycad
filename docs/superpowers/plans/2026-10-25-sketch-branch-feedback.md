# Sketch branch feedback implementation plan

> Execute inline with superpowers:executing-plans under the user's existing development authorization.

**Goal:** A successful constraint solve must visibly report detected direction, side, tangency or arc-branch changes before acceptance.

**Architecture:** Keep PlaneGCS as the solver. Add a separate deterministic geometry-comparison adapter returning neutral branch-change records alongside the solved preview. Check directional reversals, signed side changes within constraint-connected geometry, arc orientation/span, and existing circle tangency/containment branches using scale-aware tolerances. The constraint dialog highlights affected geometry and requires acknowledgement of detected changes; draft dragging displays a persistent warning through release, with cancellation and undo unchanged. Archived solutions remain frozen and are never re-solved.

**Spec:** `.omo/plans/phase2-agent-loop.md` P2-33 and `docs/design/solid-edge-interaction-acceptance.md`.

## Constraints and review focus

- Core DTOs remain stdlib-only. New comparison logic belongs in geom; no new solver or backend dependency.
- Changes from tiny numerical noise must not trigger branch feedback.
- A mirrored valid solution can have zero residual/DOF; explicitly test detection despite numerical success.
- Point-distance triangles and virtual distance segments need side checks even without drawn connecting lines.
- Uniform translation/ordinary rotation preserving signed sides must not be misclassified as a side flip; direction changes over 90° are conservatively identified as orientation changes.
- Preview acknowledgement resets after any input change. Failure/cancel must not write history.
- Draft drag warnings survive mouse release and are cleared when the current candidate no longer contains the detected change.

## Steps

- [x] Add failing detector and solver-integration tests covering reversal, mirrored triangle, tangent branch, arc branch, tolerance and benign motion.
- [x] Add `SketchBranchChange` and `SketchConstraintSolveResult.branch_changes`; implement `geom/sketch_branches.py::detect_branch_changes(before, after)`.
- [x] Attach results after residual validation for constraint add/update and draft drag.
- [x] Add constraint-dialog acknowledgement, affected-object text and preview highlighting; cover input invalidation and commit gating.
- [x] Preserve branch warning text during constrained draft drag and after release; cover undo/cancel.
- [x] Run scoped pytest/Ruff/format/basedpyright; update ADR, acceptance baseline and requirement audit.

## Reference conventions

AutoCAD documents dimension edits as re-evaluating all applicable constraints, with reference dimensions reporting measured geometry. Solid Edge describes maintained relationships during geometry edits. Those conventions support the existing solver/preview approach; the branch comparator is a MyCAD verification layer, not a claim that either product uses this implementation.

- https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-57C6FFF6-622E-431E-840F-03E8560D70B0.htm
- https://support.industrysoftware.automation.siemens.com/training/se/en/ST4/pdf/spse01510-s-1040_en.pdf
