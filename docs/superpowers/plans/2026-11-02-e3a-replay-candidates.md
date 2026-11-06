# E3-A Isolated Replay Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a reusable isolated replay candidate that combines command replacements, appended commands, and optional v5 identity upgrade, then commits exactly once through the source Bus after a successful preview.

**Architecture:** Keep proposal, failure, and confirmation data in core-neutral DTOs. The app composition root creates a candidate Document/Bus/BuildKernel with built-in handlers only, replays the frozen history, and returns a neutral display result. The source Bus signs and consumes a one-time grant, then applies the candidate change set in one event transaction with rollback and controlled replay.

**Tech Stack:** Existing Python core/app/geometry layers, BuildKernel, CommandBus, pytest, ruff, and basedpyright.

**Spec:** docs/superpowers/specs/2026-11-02-isolated-replay-candidates-design.md

## Global Constraints

- Core must not import build123d, OCP, numpy, Qt, or geom; app.py remains the only src file bridging core and geom.
- All active Document writes remain inside CommandBus; candidate construction may initialize a detached Document from copied neutral records.
- Candidate preview runs only built-in replayable commands; unsupported plugin history fails explicitly without invoking plugin code.
- v1-v5 wire rules and E2-A/E2-B contracts remain unchanged; no new archive version or implicit old-document migration.
- Existing command audit fields and timestamps are preserved; amendments append once; undo semantics remain unchanged.
- Candidate failure/cancel leaves source history, format, IDs, dirty, redo, revision, events, and geometry unchanged.
- Preserve all pre-existing E2-A/E2-B working-tree changes; do not commit or push as part of this slice.

## Review Focus

- Same command UUIDs in another runtime document or session must not authorize a candidate; pin in Task 4 with test_replay_candidate_grant_is_document_and_session_scoped.
- v4 identity upgrade with redo must use the exact proposed active/redo IDs and remain unchanged on cancel; pin in Tasks 2 and 4 with test_candidate_upgrade_reuses_signed_ids_and_preserves_redo_on_cancel.
- A failed command that mutates its scratch kernel before raising must not contaminate the reported prefix; pin in Task 3 with test_failure_prefix_replays_only_commands_before_failure.
- Re-preview must retain staged command IDs while invalidating older generations and preventing duplicate commits; pin in Tasks 3-4 with test_repreview_keeps_ids_and_expires_old_generation and test_replay_grant_is_single_use.
- Unsupported plugin history must fail at its command ordinal without running its handler; pin in Task 3 with test_candidate_rejects_plugin_history_without_calling_handler.

## File Map

- Create src/mycad/core/replay_proposal.py for frozen neutral change-set, proposal, failure, and grant DTOs plus canonical digesting.
- Modify src/mycad/core/bus.py for proposal preparation, candidate replay result capture, signed grant issuance, and atomic source commit.
- Modify src/mycad/core/document.py only if a Bus-owned helper is needed to preserve the existing single-write-path invariant for staged amendments/identity adoption.
- Modify src/mycad/app.py for ReplayCandidateSession and its isolated candidate Document/Bus/BuildKernel lifecycle; do not add fields to the four-member AppServices.
- Create tests/core/test_replay_proposal.py, tests/app/test_replay_candidates.py, and tests/geom/test_replay_candidates.py for DTO, transaction, lifecycle, and real geometry coverage.
- Add .omo/evidence/e3a-replay-candidates/acceptance.md with exact scoped commands, outcomes, and remaining E3 boundaries.

---

### Task 1: Neutral proposal and result contracts

**Files:**
- Create: src/mycad/core/replay_proposal.py
- Test: tests/core/test_replay_proposal.py

**Interfaces:**
- ReplayCandidateState = Literal["ready", "previewing", "succeeded", "failed", "stale", "committed", "cancelled"]
- ReplayEdit(ordinal: int, params: Mapping[str, object], actor: str, reason: str)
- ReplayAppend(command_id: str, version: int, params: Mapping[str, object], confirmed_by: str | None)
- ReplayChangeSet(replacements: tuple[ReplayEdit, ...], appends: tuple[ReplayAppend, ...], upgrade_to_v5: bool)
- ReplayCandidateProposal(document_id: str, file_id: str, revision: int, session_identity: int, candidate_id: str, generation: int, archive_version: int, commands: tuple[ExecutedCommand, ...], identity_upgrade: IdentityUpgrade | None, digest: str)
- ReplayFailure(command_id: str, command_version: int, instance_id: str | None, ordinal: int, parameter_path: str | None, reason: str, last_successful_ordinal: int | None)
- ReplayCommitGrant(document_id: str, file_id: str, revision: int, session_identity: int, candidate_id: str, generation: int, digest: str, nonce: str, signature: str)
- replay_digest(archive_version: int, commands: Sequence[ExecutedCommand]) -> str

- [x] **Step 1: Write failing DTO tests**

  Assert that equivalent command histories have the same canonical digest regardless of mapping insertion order; changing params, archive version, instance ID, or amendment content changes it. Assert constructors defensively copy nested mutable inputs and reject invalid generation/revision/identity values.

- [x] **Step 2: Run the DTO tests and confirm they fail**

  Run: uv run pytest tests/core/test_replay_proposal.py -q
  Expected: FAIL because the proposal module and DTO validation do not exist.

- [x] **Step 3: Implement the frozen neutral DTOs and digest**

  Keep this module free of backend, Qt, numpy, and app imports. Digest only JSON-compatible normalized data and reject non-finite or unsupported values instead of stringifying them.

- [x] **Step 4: Run the DTO tests and scoped static checks**

  Run: uv run pytest tests/core/test_replay_proposal.py -q
  Run: uv run ruff check src/mycad/core/replay_proposal.py tests/core/test_replay_proposal.py
  Run: uv run ruff format --check src/mycad/core/replay_proposal.py tests/core/test_replay_proposal.py
  Run: uv run basedpyright src/mycad/core/replay_proposal.py
  Expected: all checks pass.

### Task 2: Source Bus proposal preparation and structured candidate replay

**Files:**
- Modify: src/mycad/core/bus.py
- Modify only if needed: src/mycad/core/document.py
- Test: tests/core/test_replay_proposal.py

**Interfaces:**
- CommandBus.prepare_replay_proposal(changes: ReplayChangeSet, *, session_identity: int, candidate_id: str, generation: int) -> ReplayCandidateProposal
- CommandBus.replay_for_candidate() -> ReplayFailure | None

- [x] **Step 1: Add failing source-isolation and replay-location tests**

  Pin duplicate/out-of-range replacement rejection, normalization before proposal freeze, amendment creation in the proposal only, appended command audit/identity stability, v4-to-v5 proposal IDs matching prepare_identity_upgrade(), and structured failure ordinal/path without source mutation.

- [x] **Step 2: Run the focused tests and confirm they fail**

  Run: uv run pytest tests/core/test_replay_proposal.py -q
  Expected: FAIL because Bus preparation and candidate replay methods do not exist.

- [x] **Step 3: Implement proposal preparation without mutating the source**

  Deep-copy active history, normalize all replacements/additions before constructing the proposal, preserve old audit fields, append one amendment for each real replacement, and reuse the exact signed identity upgrade IDs when v5 is requested. Keep redo only inside the signed identity-upgrade data; do not apply that proposal to a candidate Bus.

- [x] **Step 4: Implement structured candidate replay**

  Reset the candidate kernel and execute each recorded command with its stored version and instance ID. Capture the current command directly from the loop when an error occurs; preserve structured parameter paths when provided and do not parse exception strings.

- [x] **Step 5: Run core tests and scoped checks**

  Run: uv run pytest tests/core/test_replay_proposal.py tests/core/test_command_identity.py tests/core/test_bus.py -q
  Run ruff check/format and basedpyright on modified core paths.
  Expected: all focused checks pass and legacy Bus behavior remains unchanged.

### Task 3: Isolated candidate session and exact failure prefix

**Files:**
- Modify: src/mycad/app.py
- Test: tests/app/test_replay_candidates.py
- Test: tests/geom/test_replay_candidates.py

**Interfaces:**
- create_replay_candidate(services: AppServices, loaded: LoadedDocument, *, session_identity: int) -> ReplayCandidateSession
- ReplayCandidateSession.stage(changes: ReplayChangeSet, *, current_session_identity: int) -> None
- ReplayCandidateSession.preview(*, current_session_identity: int) -> ReplayCandidatePreview
- ReplayCandidateSession.interactive_face_binding(identity: TopologyId, *, generation: int, current_session_identity: int) -> Mapping[str, object]
- ReplayCandidateSession.cancel() -> None
- ReplayCandidatePreview(state: ReplayCandidateState, proposal: ReplayCandidateProposal, viewport: ViewportData | None, sketches: tuple[ViewportSketchData, ...], failure: ReplayFailure | None)

- [x] **Step 1: Add failing isolated-session and geometry tests**

  Assert the allowed ready → previewing → succeeded/failed, stale, committed, and cancelled state transitions. Assert preview success/failure leaves source commands, archive version, dirty, redo, revision, source kernel snapshots, and events unchanged. Assert a box-to-bound-hole candidate has the expected actual hole center/radius/depth. Assert unsupported plugin history is rejected before its handler runs.

- [x] **Step 2: Add the failed-prefix contamination test**

  Use a candidate-only handler/kernel fixture that changes its scratch state and then raises. Assert the returned prefix snapshot is reconstructed on a fresh kernel using only commands before the failed ordinal.

- [x] **Step 3: Pin candidate pick ownership and stale-result handling**

  Assert a main-kernel TopologyId is rejected by the candidate kernel, a candidate pick is rejected after generation changes, and a delayed preview result cannot replace a newer staged proposal.

- [x] **Step 4: Run the new tests and confirm they fail**

  Run: uv run pytest tests/app/test_replay_candidates.py tests/geom/test_replay_candidates.py -q
  Expected: FAIL because the candidate session API does not exist.

- [x] **Step 5: Implement candidate ownership and lifecycle**

  Build a distinct Document/Bus/BuildKernel with built-in handlers only. stage freezes one full proposal; every preview advances generation while reusing its staged command IDs and audit data. Every operation checks the caller's current session identity. interactive_face_binding resolves only against the current candidate kernel and generation. On replay failure discard the failed kernel, replay only the successful prefix on a fresh kernel, and return its snapshot. cancel invalidates the session and releases candidate state. Discard any result whose generation is no longer current.

- [x] **Step 6: Run app/geometry focused tests and scoped checks**

  Run: uv run pytest tests/app/test_replay_candidates.py tests/geom/test_replay_candidates.py -q
  Run ruff check/format, basedpyright, and uv run pytest tests/test_layering.py -q on the changed paths.
  Expected: source state remains untouched and candidate geometry/failure snapshots match the assertions.

### Task 4: One-time grant and atomic source commit

**Files:**
- Modify: src/mycad/core/bus.py
- Modify: src/mycad/app.py
- Test: tests/core/test_replay_proposal.py
- Test: tests/app/test_replay_candidates.py

**Interfaces:**
- CommandBus.authorize_replay_candidate(proposal: ReplayCandidateProposal) -> ReplayCommitGrant
- CommandBus.commit_replay_candidate(proposal: ReplayCandidateProposal, grant: ReplayCommitGrant) -> None
- ReplayCandidateSession.authorize_commit(*, current_session_identity: int) -> ReplayCommitGrant
- ReplayCandidateSession.commit(grant: ReplayCommitGrant, *, current_session_identity: int) -> None

- [x] **Step 1: Add failing stale, tamper, and replay-failure tests**

  Pin rejection before replay for changed document_id, file_id, revision, session identity, generation, digest, or identity-upgrade signature; pin duplicate grant consumption; inject failure during the committed rebuild and assert original history, audit, format, dirty, redo, geometry, revision, and buffered events are restored.

- [x] **Step 2: Run the focused tests and confirm they fail**

  Run: uv run pytest tests/core/test_replay_proposal.py tests/app/test_replay_candidates.py -q
  Expected: FAIL because grant authorization and composite commit do not exist.

- [x] **Step 3: Implement source-signed, one-time grants**

  Sign source document/file/revision, session identity, candidate ID/generation, and digest with the source Bus secret. ReplayCandidateSession issues a grant only for its latest succeeded generation and rechecks the caller's current session identity at both grant and commit time. Consume nonce only after every preflight check passes; reject stale candidates before changing Document or kernel state.

- [x] **Step 4: Implement one Bus transaction for identity, amendments, appends, and rebuild**

  Apply all staged changes through Bus-owned Document helpers, validate the final archive, rebuild once, increment revision once, and publish buffered events only after success. Clear redo for content edits; preserve upgraded redo for identity-only commits. On failure use existing restore/rebuild and poison behavior.

- [x] **Step 5: Run focused core/app checks**

  Run: uv run pytest tests/core/test_replay_proposal.py tests/core/test_command_identity.py tests/core/test_bus.py tests/app/test_replay_candidates.py -q
  Run ruff check/format and basedpyright on modified paths.
  Expected: stale/reused/tampered grants reject without mutation; successful composite commits produce one revision and one amendment per changed command.

### Task 5: E3-A acceptance evidence and regression boundary

**Files:**
- Modify: docs/design/n3-e3-next-task-todo-2026-11-02.md
- Create: .omo/evidence/e3a-replay-candidates/acceptance.md
- Test: affected existing core/app/geometry suites only

**Interfaces:**
- Evidence records the exact command lines, pass/fail outcomes, and any remaining E3-A boundary. Mark only completed E3-A TODO rows; do not mark E3 or P2-12/19 complete.

- [x] **Step 1: Run the targeted integration matrix**

  Cover v4 plus redo cancellation, repeated preview identity stability, v4 upgrade plus bound-hole append, multi-edit repair of an upstream/downstream pair, failure at each replay position, stale session/source, digest tampering, duplicate commit, commit-time rollback, and plugin-history rejection.

- [x] **Step 2: Run scoped project checks**

  Run the relevant tests under tests/core, tests/app, and tests/geom, plus tests/test_layering.py; run ruff check/format and basedpyright on every modified path. Do not repeat already-confirmed unrelated suites or run the full repository suite for this slice.

- [x] **Step 3: Record acceptance evidence and update the task TODO**

  Record exact outputs and limitations. Keep E3-B/C/D, split/merged repair, whole-repair undo, and P2-12/19 marked incomplete.

- [x] **Step 4: Review the final diff for scope and dirty-state preservation**

  Confirm no existing E2-A/E2-B edits were overwritten, no plugin execution was introduced, no Document write bypassed Bus, and no protected layering path or archive contract changed.
