# Sketch consumer rebuild implementation plan

> Execute inline with superpowers:executing-plans; the user has authorized continued development without another approval gate.

**Goal:** A confirmed sketch constraint regenerates existing solid features, with deterministic replay and atomic failure recovery.

**Architecture:** Introduce `sketch.constraint.add@3` with a required-by-default regeneration policy; retain @1/@2 semantics. The geometry adapter retains successful operation inputs. Regeneration uses an isolated kernel, current frozen sketch solutions, original feature order and freshly resolved support planes; it never invokes a solver. Install the result only after the complete rebuild succeeds. The Bus remains the sole document writer and owns rollback/undo/redo.

**Tech Stack:** Python, build123d/OCCT, existing CommandBus, pytest.

**Spec:** `.omo/plans/phase2-agent-loop.md` P2-36; `docs/design/solid-edge-interaction-acceptance.md`.

## Global constraints

- Preserve old versions, audit fields, history order and stored solutions.
- No backend imports outside geom; no direct Document mutation.
- Preserve the shared working tree. No automatic commit.
- This repair does not complete the remaining P2 G audit or existing-dimension UI work.

## Review focus

- A constraint after extrusion must change both sketch and volume.
- Undo/redo and reopen must reproduce the result without PlaneGCS.
- Invalid downstream features must restore commands, sketches and geometry.
- Multiple sketch consumers and attached sketch planes must regenerate in feature order.
- @1/@2 archives keep their prior append-only semantics.

## Task 1: Versioned downstream regeneration

Files: `src/mycad/builtin_commands/specs.py`, `src/mycad/geom/kernel.py`, `tests/geom/test_sketch_constraints.py`.

- [x] Add a regression: radius 5 circle, distance 10 extrusion, radius 7 constraint; assert volume `490π`, undo `250π`, redo `490π`, reopen without solver `490π`.
- [x] Run the regression and record its failure.
- [x] Add @3 schema, `rebuild_consumers` boolean const/default true. Record deep-copied successful kernel operation inputs, reset/copy them with kernel state.
- [x] Rebuild in a scratch kernel from recorded feature inputs, substituting final frozen sketches immediately after each original creation and skipping already validated constraint events. Resolve attached planes in feature order. Preserve historical snapshots; install final part/sketches only after success and append one constraint snapshot.
- [x] Add old-version, multiple-consumer and downstream-failure regressions; run scoped pytest, Ruff and basedpyright.

## Task 2: Continue original scope

- [x] Integrate full solid preview/error feedback with the constraint dialog.
- [x] Implement existing driving-dimension revision and its complete replay/UI evidence.
- [ ] Reconcile the remaining rows of `.omo/evidence/task-P2-G-requirements-audit.md` before final acceptance handoff.

### Existing dimension revision implementation

- Add `Sketch.with_updated_constraint(constraint, entities)` for a dimension with an existing identity. Preserve its kind, references, source, ordering and all other constraints. Numeric value, driving/reference mode and formatting may change.
- Add `solve_sketch_constraint_update(sketch, constraint)`: retain current geometry as the solver seed, replace only the selected relation during solving, restore constraint order and refresh measured reference dimensions. Expose through `BuildKernel.preview_sketch_constraint_update`.
- Release `sketch.constraint.update@1` with the same frozen-solution and base-state hash contract as add@3. Append one audited command through Bus, preserve original history, rebuild downstream from frozen solutions; no solver calls during replay. Permit the command in drawing2d documents and update explicit catalog tests.
- Add an existing-dimension selector to the constraint dialog; show its current value/mode/format, preserve identity/reference fields, use the existing asynchronous whole-model preview and explicit confirmation.
- Regression gates: numeric change with a later fixed relation/reference dimension, geometry invalidation rollback, missing/mismatched identity rejection, undo/redo/reopen with solver disabled, drawing document support, GUI preview/cancel/confirm and stale preview protection. Run scoped pytest, Ruff, format and basedpyright.
