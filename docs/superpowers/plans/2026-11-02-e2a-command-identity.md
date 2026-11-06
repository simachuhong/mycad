# E2-A Command Identity Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. User authorized E2-A implementation on 2026-11-02; work in the existing feature checkout containing its uncommitted prerequisites.

**Goal:** Persist command instance identity without changing old archive semantics, and preserve it throughout Bus and geometry regeneration.

**Architecture:** Optional instance_id on ExecutedCommand; required canonical hex UUID in v5. Bus prepares signed revision-bound upgrade proposals for active and redo commands. Contextual kernels retain immutable command context together with each operation; legacy apply remains compatible.

**Tech Stack:** Python, locked build123d/OCP, pytest, strict basedpyright.

**Spec:** docs/design/n3-e2-identity-and-replay-analysis-2026-11-02.md.

## Global Constraints

- v1–v4 wire rules and six audit fields remain unchanged; v5 adds command instance_id.
- No new hole version, binding consumer, reserved command ID or GUI flow.
- Upgrade, cancellation and failures preserve identity/history/redo/geometry atomically.
- Reuse current checkout; no commit or push. Scoped checks per AGENTS.md.

## Review Focus

- Stale/tampered upgrade proposal must not mutate the document.
- Old-format commands and existing fake kernels/plugins remain executable.
- Save As and preview preserve existing command identities without downgrading.
- Nested snapshots retain exact fingerprints; v4 cannot adopt v5 silently.
- Sketch/reference regeneration and candidate replacement retain context.

## Task 1: Identity and archive contract

- [x] Write failing tests in tests/core/test_command_identity.py for explicit upgrade, redo identity, tampering, archive round trip and invalid UUIDs.
- [x] Add core/command_identity.py, core/schema_v5.py and version dispatcher; extend ExecutedCommand with optional instance_id.
- [x] Implement version-specific persistence with unchanged legacy serialization and min archive preflight.
- [x] Record ADR-014 for the approved per-command identity approach and its limitations.

## Task 2: Bus and handler propagation

- [x] Implement prepare_identity_upgrade() and apply_identity_upgrade(proposal), with HMAC and monotonic revision checks and rollback.
- [x] Allocate IDs only on new v5 execution; reuse recorded IDs during rebuild. Reject missing identities and duplicate IDs.
- [x] Add optional contextual kernel protocol, handler propagation and tests for legacy compatibility, amendment audit and rollback.

## Task 3: Geometry and application lifecycle

- [x] Add immutable ExecutionContext and operation records; retain them through reference updates, sketch regeneration and candidate swaps.
- [x] Add tests/geom/test_command_identity.py for real geometry, preview, Save As, nested snapshots and failures.
- [x] Replay existing records in preview rather than executing them as new commands; preserve version and identity on Save As.

## Task 4: Verification

- [x] Run scoped core/geometry/UI document/version/reference tests and static checks; preserve pre-existing dirty edits.
- [x] Independent final review, fix meaningful findings, record evidence and remaining E2-B boundaries.
