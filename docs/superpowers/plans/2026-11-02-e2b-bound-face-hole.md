# E2-B Bound Face Hole Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven-development. User authorized E2-B development; reuse the current feature checkout and its uncommitted E2-A prerequisites.

**Goal:** A real v5 Bus hole binds to a primitive face and preserves source-relative hole position across replay, edit and save/open.

**Architecture:** feature.hole@3 is a compatible superset of @2. Only its bound-face branch requires v5 and a binding-capable kernel. Neutral BoundFaceRef stores source_instance_id and a primitive role; geometry reconstructs a conservative lineage map from actual native operation inputs and fixed source frames.

**Tech Stack:** Python, locked build123d/OCP, existing native Boolean history, pytest and strict basedpyright.

**Spec:** docs/design/n3-e2-identity-and-replay-analysis-2026-11-02.md and the approved Solid Edge assessment. This plan resolves the version/position choices left for E2-B.

## Global Constraints and decisions

- Keep registry latest-version policy and all old query/sketch branches; do not alter hole@1/@2 schemas.
- Binding wire: `{kind: bound_face, source_instance_id: canonical hex UUID, role: box.+X/.../box.-Z or cylinder.top/bottom}`. Roles define a planar primitive face; no persistent result indices.
- Bound position accepts legacy center/point (their existing meaning) or `{kind: local, uv_mm: [u,v]}`. Local frame origin is the primitive face center before trimming; u is global +X for Z faces and global +Z for X/Y faces, v = normal × u.
- Box and cylinder creation/replacement, native primitive add/cut, hole and inline boolean_cut are the first supported lineage paths. Splits/merges/deletion/unknown or unsupported geometry changes fail with a located reason. New generated cut faces are not bindable.
- Primitive add uses exact native fuse history in the v5 identity-aware path so disjoint equal/size-flipped bodies stay distinguishable. Old nonidentity paths retain their backend operations.
- Local points must lie in the current finite face region; no nearest/rank fallback or silent projection.
- No GUI repair workflow (E3), edge binding, new archive version or reserved command ID. Explicit v5 upgrade remains E2-A's separate step.

## Review Focus

- Same-looking bodies and size reversal must preserve the selected source or fail.
- New/old command versions and legacy kernels must not silently acquire binding semantics.
- Failure must restore geometry, audit, history and redo; errors carry command/parameter/ordinal.
- Candidate replacement and internal regeneration must retain native face identity with the correct part.
- Stale or foreign picks and unsupported/generated faces cannot mint a misleading reference.

## Task 1: Wire and real command tests

- [x] Add failing tests for hole@3 registration, old query compatibility, conditional v5 requirement, bound local hole and save/open/replay.
- [x] Implement core/bound_refs.py and a released compatible hole@3 schema. Share conditional archive requirement between Bus and archive preflight; reject binding on legacy kernels.

## Task 2: Geometry lineage and stable placement

- [x] Add geom/design_faces.py with immutable tracked face/frame states. Seed roles from the exact primitive source; advance only by native history and postconditions.
- [x] Extend identity-aware primitive operations with optional source/history capture. Connect tracker to successful kernel commits, replacement, reference and sketch regeneration.
- [x] Resolve bound hole to exact native face, construct world point from source frame for local placement, reuse actual cutter/cut implementation without changing history params.

## Task 3: Pick and failure regression

- [x] Add live TopologyId-to-bound-reference API without query/rank conversion.
- [x] Test two cuts, size flip/equal bodies, asymmetric trimming, all planar role frames, source deletion/replacement, split/merge, missing/forward owner, unsupported operations and stale/foreign picks.
- [x] Check actual hole center/diameter/depth and audit/undo/redo/archive/preview rollback, not only whole volume.

## Task 4: Verification and evidence

- [x] Run scoped command/core/geometry/CLI tests, affected UI consumers, lint/format/types and layering guards.
- [x] Independent final review; fix meaningful findings with regression tests.
- [x] Record exact supported boundaries and evidence, retaining P2-12/19 partial until E3 and remaining matrices close.
