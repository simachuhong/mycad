# ADR-013 — Independent document ownership and save sessions

Status: Accepted 2026-10-29

## Context

The user approved the independent-document design and implementation plan. Workspace
selection previously shared one history/path, causing incorrect suffixes and save state.

Supersedes ADR-012's shared part/drawing archive ownership; retains its projection,
annotation and output architecture. Extends ADR-011 without changing v1/v2/v3 wire rules.

## Decision

- Desktop workspaces select editable documents. A session is keyed by runtime document ID,
  can hold multiple documents of each kind, and gives every editable document its own
  services/kernel, Bus, history, file path, modified state and editor/view state.
- V4 adds stable `file_id` and explicit `document_kind` (`sketch`, `drawing`, `part`).
  Sketch/drawing native files use `.my2d`, parts use `.my3d`. Model-internal sketches belong
  to their part. A tab switch cannot mutate an existing document's kind.
- `reference.attach/update/detach` adopt immutable, validated command-history snapshots.
  A referenced sketch becomes a read-only internal instance until explicitly detached.
  Updates replay through the Bus, regenerate consumers in isolation and are undoable.
  No replay performs filesystem/network reads. Engineering drawings can adopt a part
  and/or sketch sources and retain their adopted versions if external files disappear.
- Locator paths are independent of file identity. V4 `reference_locations` records saved
  source paths relative to the referring file, with an absolute fallback for different
  Windows drives. It takes precedence over the original command's path hint. It does
  not amend model parameters or silently adopt newer geometry.
  Save As rebases locators even when sources are closed. Opening inspects identity/kind
  and reports missing or mismatched sources without changing adopted geometry.
- Ordinary Save affects the selected document. Save All stages draft completion and
  filename/overwrite choices before writing, orders documents by their reference graph,
  and reports saved/failed/cancelled/pending results. A multi-file save is not atomic;
  each individual replacement remains atomic. Successful files alone become clean.
- Save As creates a new file identity and replaces the current editing entry after the
  write succeeds. Existing referrers keep the original identity and snapshot. Its
  identity-only aggregate replacement reuses that entry's unchanged geometry; it is
  never exposed as a second editable document sharing the same kernel.
- Closing collects per-document save/discard decisions and destroys nothing until all
  requested saves succeed. Any cancellation or failure leaves all unclosed documents in
  memory, including those tentatively marked for discard.
- Legacy mixed archives are validated and replayed in isolated candidate services before
  migration. Model/internal-sketch history and paper history become separate candidates.
  New local ordinals are contiguous; `migration_origin` retains the full original archive,
  including the original six audit fields and amendments. Original files are untouched.
  A persisted migration origin is historical provenance, not a fresh-migration flag;
  reopening saved v4 files preserves their paths. Explicit internal-sketch separation
  creates an independent 2D copy with no model-face support, preserving model history.
- Existing single-document MainWindow embedding remains supported; the desktop entry
  supplies DocumentSession. GUI CLI new/open/save are routed to the file menu to preserve the
  multi-document lifecycle; standalone CLI interfaces retain their prior semantics.

## Assembly boundary

`.masm` stays reserved and is rejected by current native open/save flows. The future
assembly document will own instances, placements and constraints while referencing
independently saved component definitions. Generic save ordering already supports
shared children, nested assemblies, drawings and cycle rejection. Ordinary assembly
Save As will retain component references; copying the complete dependency set requires
a separate future packaging operation.

## Consequences

V4 readers are required for new desktop archives. Snapshot-based references increase
file sizes but keep deterministic replay and recovery independent of source availability.
No BREP snapshot replaces command history. Source adoption is explicit, so users can save
a source and a drawing that intentionally use different adopted revisions.

## References

See the [approved design](../superpowers/specs/2026-10-28-document-save-ownership-design.md)
and [implementation plan](../superpowers/plans/2026-10-28-document-save-ownership.md).
