# U09 Cross-Sketch Tangency Implementation Plan

**Goal:** Preserve and solve tangent relations between entities owned by different sketches.

**Architecture:** Record stable sketch/entity references and an explicit tangency branch in versioned, replayable document commands. Resolve connected sketches into a common plane and solve one component; stage all changed sketches and relation changes in one Command Bus candidate. Existing per-sketch constraints and old command versions retain their semantics.

**Spec:** `docs/design/2026-11-07-cross-sketch-fillet-remaining.md`.

## Constraints and review focus

- Never put dangling cross-sketch references into an existing sketch-local constraint.
- Reject missing or ambiguous entity ownership, noncoplanar frames, incompatible constraints and unsatisfied branches.
- Detect stale revisions and ensure candidate failure, cancellation and undo do not commit a partial component.
- Preserve entity and sketch identities across revision, replay, archive upgrade, delete and document switching.
- Test flipped coplanar frames, chains and cycles, user locks, downstream dependencies, save/reopen and replay.

## Tasks

- [x] Implement strict document relation records and deterministic connected-component resolution.
- [x] Implement frame projection and branch-aware temporary compound solving, including conflict tests.
- [ ] Add versioned commands and atomic candidate staging for create, edit and delete of affected sketches.
- [ ] Finish connecting automatic fillet relations and later sketch edits, protecting existing constraints and locks. Automatic trimmed and non-trimmed fillets and saved or mixed MOVE/ROTATE/MIRROR now use the relation model in supported cases; dragging, dimensions and further mixed combinations remain.
- [ ] Verify failures, undo/redo, save/reopen, replay, stale revisions and dependency rebuilds.

## Persistence design

`drawing.tangency.add` must atomically carry a strict relation record and frozen sketch revisions with base digests. Prepare all revised sketches without changing the live kernel, independently validate every existing and proposed cross-sketch relation on the complete candidate, rebuild consumers once, and only then install the candidate through the Bus. Maintain relations in kernel state copied by reset/open/rebuild. Regeneration installs final sketch states at creation and restores the final relation set rather than replaying intermediate relation commands against partially constructed sketches. Existing single and batch revision paths, dimension updates and reference changes must reject any resulting dangling or unsatisfied relation until they can propose a whole-component solution. Add removal as an explicit replayable command before allowing source deletion. No UI integration until all these guards, undo/redo and old-archive replay are tested.
