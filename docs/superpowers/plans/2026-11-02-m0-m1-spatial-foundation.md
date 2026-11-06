# M0/M1 Spatial Foundation Implementation Plan

> Execution: superpowers:executing-plans, native in this session; no commits unless separately requested.

**Goal:** Implement a replayable relative coordinate system → principal/offset datum plane → associated planar sketch → extrusion chain.

**Architecture:** Immutable neutral rigid frames and document-local command instance references; v6 commands evaluated in history order through Bus, with isolated candidates and atomic migration. Plane sketches retain local UV and derive their world frame from replayed support.

**Tech Stack:** Python, existing Command Bus, build123d/OCCT, JSON archives, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-3d-modeling-foundation-design.md`.

## Global Constraints

- No CAD backend or numpy in core; no Qt outside ui; app.py is the core/geom composition root.
- Model edits only through Bus; preserve v1–v5 and six audit fields, instance IDs and redo.
- Rigid right-handed frames only; XZ preserves existing U=+X,V=-Z,N=+Y convention.
- New `datum.*` identifiers are reserved until the ADR explicitly activates them for M1.
- GUI workbench M2, E3-B and actual spatial XYZ sketches remain separate later packages.

## Review Focus

- Reject NaN, non-unit/non-orthogonal, left-handed or degenerate axes before mutation.
- Reject missing, wrong-role, forward and cyclic references without nearest-geometry fallback.
- Preserve source version, redo, audit and geometry on cancelled or failed v6 migration.
- Rebuild datum state during undo, redo, open, candidate, reset and replace_state_from.
- Source edits change dependent world geometry but not sketch local coordinates; check save/reopen.

## Tasks

- [x] M0.1: tests in `tests/core/test_spatial_frames.py` demonstrate parent/child rigid composition, inverse, principal-plane orientation and invalid frames; implement neutral `src/mycad/core/spatial_frames.py` with `RigidFrame`.
- [x] M0.2: ADR-016 defines v6, command names/versions, tagged references and migration; implement strict schema and archive version dispatch, covering v1–v5 and malformed/duplicate identities.
- [x] M0.3: extend `core/replay_proposal.py`, `core/bus.py`, `app.py` candidate migration to explicit target v6 while preserving existing v5 API; test stale, cancellation, redo and failure rollback.
- [x] M1.1: register `datum.coordinate_system.create@1` and `datum.plane.create@1`, replay identity-scoped parent/principal/offset definitions; test missing/forward references and state lifecycle.
- [x] M1.2: add versioned associated sketch support with stored UV placement and deterministic frame resolution; preserve legacy sketch command versions and frame behavior.
- [x] M1.3: exercise real kernel and Bus end-to-end with parent modification, undo/redo, save/reopen, candidate commit and migration failure, using independently derived exact expected geometry.
- [ ] M1.4: run scoped ruff, format, basedpyright, tests and layering, followed by full final integration checks; record results and limitations in progress docs.

## 2026-11-02 implementation progress

M0.1 is implemented with scoped tests: rigid composition/inverse and XY/XZ/YZ frames, strict typed source references, and evaluation of relative coordinates and principal/offset planes. These are pure domain utilities, not registered modeling commands. ADR-016 records the proposed v6 contract; archive dispatch, Bus migration and all M1 integration remain open. The GUI cannot yet create coordinate systems or datum planes.

## 2026-11-02 M0/M1 implementation update

The development API now supports archive v6, signed candidate target-version migration, `datum.coordinate_system.create@1`, `datum.plane.create@1`, and associated `sketch.create@4`. A relative coordinate chain can drive a principal/offset plane, a local sketch, and extrusion through Bus replay. Save/reopen, Save As, redo, invalid references, candidate rollback, nested archive version guards, and downstream sketch-constraint regeneration have targeted coverage. Independent review identified and verified the fix for old sketch CLI compatibility.

M1.4 remains open until full integration validation finishes. The M2 independent three-dimensional sketch workbench, datum UI/picking, associative bound-face support, and non-coplanar spatial sketches remain separate work; no GUI completion is claimed.

## Integration validation record

See [M0/M1 acceptance evidence](../../../.omo/evidence/m0-m1-spatial-foundation/acceptance.md). Full pytest initially produced 2463 passes and 13 failures; the failures were addressed and rerun by scope, including an isolated passing performance check. A full-suite green run on the final worktree has not been established; M1.4 remains open.
