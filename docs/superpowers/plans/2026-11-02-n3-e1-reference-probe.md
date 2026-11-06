# N3 E1 Reference Probe Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for the approved E1 experiment. This is a test-only geometry prototype, not a shipped N3 implementation.

**Goal:** Verify real source-face lineage across two Boolean operations and distinguish face-centroid placement from a fixed local placement intent.

**Architecture:** Keep the probe entirely under tests/geom. Carry the exact source shape and selected face between operations; locate by native IsSame, consume native evolution, reject uncertain relations. Reconstruct the experiment from a symbolic primitive role for size perturbations; do not serialize runtime indices.

**Tech Stack:** Locked build123d/OCP, pytest, existing boolean_with_evolution.

**Spec:** docs/design/n3-solid-edge-benchmark-2026-11-02.md, E1 only.

## Global Constraints

- Reuse the current feature-branch checkout because the prerequisite topology prototype is uncommitted here.
- No product command, persistence schema, GUI or existing selection semantics change in E1.
- Source geometry is the exact operation input; independently constructed lookalike shapes are not interchangeable.
- Native history absence, split, merge and deletion must not silently select a candidate.
- Project scoped verification takes precedence over skill full-suite defaults. No commit/push is part of this experiment.

## Review Focus

- Same-looking independent source shapes must fail binding validation.
- Two successive cuts must use the immediately preceding result indices.
- Plane normals, finite local points and actual face containment must be checked.
- Split/merge/deletion must leave the previous probe state unchanged.
- Size reversal and asymmetric material removal must not silently move the intended hole.

## Task 1: Exact-input lineage experiment

Files: create tests/geom/test_design_reference_probe.py and tests/geom/design_reference_probe.py.

Interfaces: bind_top_face(shape: Part) -> Face; advance_face(shape: Part, face: Face, tool: Part, operation: BooleanKind = "cut") -> tuple[Part, Face]; local_point_on_face(face: Face, frame: Plane, uv: tuple[float, float]) -> tuple[float, float, float]. All APIs are explicitly test-only.

- [x] Write failing cases for two real cuts, wrong source face, split, merge, deletion and missing mapping.
- [x] Run the new file and verify missing helper failure.
- [x] Implement the test-only prototype using native face identity and operation-local evolution.
- [x] Assert resulting face normal, area/position and immutable input behavior; run scoped tests.

## Task 2: Placement and rebuild experiment

- [x] Add tests for asymmetric trimming moving face centroid while a defined local point stays fixed, out-of-face/nonfinite points, changed source height and size reversal across two bodies.
- [x] Implement local planar point checking and reject unsupported alignment.
- [x] Independently rebuild after size changes using the primitive role; verify source location and actual drilled cylinder center, diameter and depth/volume.
- [x] Run scoped pytest plus lint/format/type on the new files; include layering checks.

## Task 3: Evidence and decision

- [x] Record commands, observations and limitations in .omo/evidence/n3-e1-reference-probe-2026-11-02.md.
- [x] Update design with evidence, distinguishing geometric re-resolution from persistent command identity and a real Bus replay.
- [x] Obtain independent review of only this experiment; resolve correctness findings with targeted tests.
- [x] Record the recommendation for E2; do not choose v5 from E1 results alone.

Execution authorization: the user requested the next step after the Solid Edge assessment; E1 is the explicitly proposed technical experiment. Product implementation and the E2 schema decision remain separate deliverables.
