# ADR-010 — Sketch solver adapter and replay contract

Status: Accepted 2026-10-25

## Context

P2-33 needs constraints that move sketch geometry, report remaining degrees of freedom, and identify redundant or conflicting constraints. A UI-only constraint overlay would misrepresent design intent. The candidate solver must be isolated from `core`, usable on supported T1 systems, and replayable through the Bus history. P2-33 also needs an explicit license and platform decision before solver code is shipped.

The restricted Linux x86-64 / CPython 3.12 prototype used `planegcs==0.9.6`. A fixed point plus a horizontal line and 10 mm point-to-point distance solved to `(10, 0)` with zero degrees of freedom. Adding a vertical constraint to the same line returned `Failed`; diagnosis identified the horizontal, distance, and vertical constraints as conflicting. Two fresh builds from identical inputs returned identical point values. Starting the same constrained line with its other endpoint on the opposite side of the fixed point instead solved to `(-10, 0)`, demonstrating that zero degrees of freedom does not establish a unique solution and the initial geometry controls the branch.

The wrapper exposes FreeCAD PlaneGCS and is licensed LGPL-2.1-or-later. Its 0.9.6 wheels cover CPython 3.12–3.14 on Windows x86-64 and manylinux x86-64. Its source distribution documents Eigen3 and Boost build requirements; an aarch64 build and T2 runtime were not verified. SolveSpace was not selected because its upstream project is GPLv3-or-later.

## Decision

1. **Select PlaneGCS behind a replaceable adapter.** The first backend is `planegcs==0.9.6`, installed only through the explicit `sketch-constraints` extra. It is optional and imported inside `geom`; importing or using unconstrained sketches never imports it. Unsupported platforms report solver unavailability and do not silently approximate constraints.
2. **Keep durable meaning in MyCAD data.** Core constraint records use MyCAD stable constraint IDs and references to stable entity IDs plus named sub-elements such as line start/end and circle center. Raw PlaneGCS integer IDs never enter the archive. Core retains only standard-library DTOs; all third-party solver types and calls stay in `geom`.
3. **Commit one confirmed constraint at a time.** Constraint creation is a disposable preview. Apply submits exactly one `sketch.constraint.add@1` command through the Bus; Cancel writes nothing. A failed or conflicting solve keeps the accepted sketch unchanged and leaves the constraint available for correction or cancellation. `sketch.constraint.add@2` adds optional dimension precision (0–8 decimal places) and display scale (0.1–100) to the durable dimension record; @1 remains frozen. Undo and redo operate on that command through full history replay.
4. **Preserve solution branch and replay.** Every preview starts from the latest accepted coordinates, not a global default. Each successful constraint command records its normalized constraint and complete solved sketch coordinates as command data. Replay restores those recorded coordinates without re-solving them. A later edit or new constraint invokes the installed adapter from the recorded accepted state. The archive provenance records solver package/version; a different solver version never silently rewrites an existing solution. Re-solving old history requires an explicit future migration.
5. **Report status honestly.** Show degrees of freedom together with solve status. Also report redundant and conflicting constraint IDs and entity references from solver diagnosis. Zero degrees of freedom is not presented as proof of uniqueness or correct design intent. A failed solve never commits partial solver output. Reference dimensions are non-driving; unsupported or ill-typed relationships are rejected before preview.
6. **Start with a tested subset.** P2-33 initially enables coincidence, horizontal/vertical, parallel/perpendicular, tangency, concentricity, equality, fixed points, and length/distance/angle/radius/diameter dimensions for line, polyline, circle, arc, and rectangle primitives. A relationship unavailable for the referenced geometry is explicitly disabled. Auto-inferred constraints remain visibly distinct from user constraints and dimensions.
7. **Set units and independently verify solver residuals at the adapter boundary.** Persisted sketch geometry and driving length values use mm; angles use degrees. Convert angle values once at the adapter boundary. The wrapper does not expose PlaneGCS native tolerances, so MyCAD independently rejects dimensional residuals above max(1e-12 mm, sketch_extent × 1e-9) or 1e-7°. It also checks driving geometric relations using max(1e-7 mm, sketch_extent × 1e-9) for positional/length residuals and 1e-7° for directional residuals. Tangency to an arc is accepted only when the contact lies within that arc's swept section. x86-64 dimension probes at 0.01, 1, 1000, and 100000 mm pass; the 1000000 mm aligned-length sample also passes with the temporary edit anchoring introduced below. Horizontal-relation solver probes at 0.01, 1, 1000, and 100000 mm pass. Relation tests also cover line/curve and curve/curve tangency plus a negative case outside the referenced arc sweep; larger relation-scale coverage and desktop workflows remain acceptance work.
8. **Keep T2 usable without the optional binary.** T1 x86-64 CI installs the explicit extra and exercises the adapter. aarch64/T2 installations do not attempt an unverified source build; they retain ordinary sketch drawing and clearly disable solver-backed constraints until an aarch64 build and replay matrix pass. This is a platform capability limit, not a core-layer exception.
9. **Ship license evidence with the optional component.** NOTICE identifies the Python wrapper and LGPL-2.1-or-later license, and the installed package's license text remains available. The extension module stays a separate dynamically loaded file. Before bundling it in a native desktop distribution, verify the applicable license notices, source availability, and replaceability requirements for that delivery format.

## Consequences

### Visible branch feedback (2026-10-25)

After independent residual validation, `geom/sketch_branches.py` compares accepted and candidate coordinates. It reports segment/distance direction changes over 90°, signed-side changes within constraint-connected components (including virtual point-distance edges), near-degenerate transitions, arc sweep/span changes, and existing circular tangency/concentric nesting changes. Positional comparisons use max(1e-7 mm, combined sketch extent × 1e-9); arc span comparisons use 1e-7°. This is a conservative geometry check, not a proof that all solutions have been enumerated or are unique. A large rigid rotation may legitimately trigger the direction warning.

Results carry neutral, transient branch records with affected stable entity IDs. The constraint dialog lists changes, highlights corresponding candidate curves in amber and requires acknowledgement before submitting. Editing any input invalidates that acknowledgement. Draft drags display detected changes during motion and after release; Esc restores the original geometry and ordinary draft undo restores the accepted prior state. Detection does not alter the frozen archive solution or invoke a solver during replay. Evidence: `task-P2-33-branch-feedback.md`.

### Existing dimensions and downstream regeneration (2026-10-25)

`sketch.constraint.add@3` adds an explicit, mandatory regeneration policy while retaining @1/@2 semantics. `sketch.constraint.update@1` revises an existing numeric dimension, preserving its stable identity, kind, references, source and order. The UI first solves against current coordinates with the old dimension replaced, then previews the complete downstream model in an isolated kernel. Confirmation appends one audited update command; original history entries and their timestamps remain intact. The frozen solution and base-state digest use the same contract as addition. Undo, redo and reopening restore the stored solutions without invoking PlaneGCS.

Reference annotations are measured from the accepted solved geometry after new @3 constraints or dimension updates, so they cannot retain stale values or falsely block a driving-dimension change. This measurement is deterministic geometry inspection, not constraint solving. Downstream reconstruction uses current frozen sketch solutions in original feature order, resolves support planes against rebuilt upstream geometry, and installs its candidate only after complete success. The Bus handles atomic rollback. The editor's direct geometry manipulation remains limited to unsubmitted drafts; existing numeric dimension revisions are available through the constraint dialog.

- The solver is testable and replaceable without changing the core sketch model or the command contract.
- The first supported solver capability is limited to T1 x86-64 until aarch64 source builds and replay behavior have evidence.
- Dimensional and supported geometric-relation residual checks are explicit at the adapter boundary. Auto-inference, live drag solving, cross-scale calibration, aarch64 build/replay, and desktop interaction remain acceptance items.
- Initial branch state is user geometry; a later edit can legitimately produce a different branch only after an explicit preview and confirmation.
- The constraint command stores solved coordinate data, so redo and archive replay do not depend on future solver versions. New solves still require a compatible installed backend.
- The optional LGPL component adds NOTICE and packaging work. Its presence does not change MyCAD's source license, but each distribution format must preserve the separate component boundary and satisfy its license terms.

## References

- [ADR-001](ADR-001-command-bus-and-history-replay.md) — single write path and deterministic command replay.
- [ADR-003](ADR-003-extension-points-and-plugin-api-versioning.md) — released command ID and version policy.
- [ADR-009](ADR-009-sketch-archive-v2.md) — sketch identities, v2 provenance, and migration rules.
- [P2-33](../../.omo/plans/phase2-agent-loop.md) — initial constraint capability and acceptance tests.
- [planegcs 0.9.6 on PyPI](https://pypi.org/project/planegcs/) — wheel matrix and source distribution.
- [planegcs upstream](https://github.com/spookylukey/planegcs) — PlaneGCS wrapper API and LGPL-2.1-or-later statement.
- [FreeCAD PlaneGCS source](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Sketcher/App/planegcs/GCS.h) — upstream solver source license.
- [FreeCAD license](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/License.md) — project source license statement.
- [SolveSpace license](https://github.com/solvespace/solvespace/blob/master/CONTRIBUTING.md) — GPLv3-or-later, not selected.


### In-canvas driving and temporary edit anchors (2026-10-26)

New canvas dimensions default to driving, with an explicit reference switch. The optional `anchor_mode` dimension metadata is `auto` (omitted for legacy compatibility), `start`, `end`, or `symmetric`; only linear dimensions accept explicit endpoint policies. During an edit, the adapter may add temporary fixed-point or midpoint gauges to PlaneGCS. They are not persisted as geometric relations, do not participate in later unrelated edits, and are excluded from the reported persistent-system degrees of freedom. Auto honors fixed/locked geometry in the constraint component first, otherwise holds the first measured point or radial center; angles retain their first edge. Explicit policies never relax existing constraints.

PlaneGCS `difference(param1, param2, value)` defines `param2-param1=value`; projected dimensions use that argument order and independently validate the resulting signed displacement. Non-ordinate projections retain their seeded direction; ordinate dimensions retain the requested sign. This corrects the prior reversed horizontal/vertical result while leaving archived frozen coordinates unchanged. Constraint edits still preserve IDs, annotation layers and positions, with Bus history recording only the accepted solution and dimension metadata.
