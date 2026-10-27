# ADR-008 — Persistence reproducibility and recovery contract

Status: Accepted 2026-10-24

## Context

`.mc.json` v1 stores a replayable command history and document annotations. It does not contain BREP snapshots, a durable document identifier, stable feature/body/topology identifiers, a complete operation log, or the application and geometry environment that interpreted the history. `FeatureId`, `BodyId`, `TopologyId`, and `Document.document_id` are runtime-scoped. The profile/work-plane value prototype is not part of archive v1.

The current writer serializes a same-directory temporary file, flushes it, and replaces the target with `os.replace`. The UI clears the document dirty flag only after `save_document` returns successfully. This protects the prior target from serialization/write/replace errors before a successful replacement, but there is no file or directory `fsync`, backup chain, autosave journal, or restart recovery service.

## Decision

1. **Keep v1 frozen.** Its exact top-level keys remain `format`, `version`, `metadata`, `commands`, and `named_groups`; its command audit fields remain `id`, `version`, `params`, `ordinal`, `timestamp_utc`, and `confirmed_by`. Optional `amendments` retain their existing append-on-edit meaning. No profile data, persistent IDs, dependency provenance, BREP, or enterprise fields are added to v1.
2. **Define the v1 replay guarantee narrowly.** The command id/version pairs identify the parameter/handler contract available to the current registry. They do not identify a plugin distribution build, MyCAD source revision, Python build, build123d/OCP/OCCT build, or every geometry policy. v1 archives therefore support compatible command replay, not bitwise BREP, STEP, mesh, or cross-version numerical identity. Geometry acceptance remains tolerance-based and must be stated by the consuming workflow.
3. **Separate model history from operation audit.** `commands` is the current replayable model state. Undo removes commands from that state; redo restores them; `amendments` records parameter edits that remain in history. This is not a complete append-only audit log of every command that was attempted, undone, redone, or rejected. A future immutable operation log is a separate product feature and is not implied by v1.
4. **Keep identity runtime-only until a consumer requires persistence.** `Document.document_id` and feature/body/topology IDs identify one live in-memory/replay scope. Save As writes the current command state to the selected path without changing the live document identity; reopening creates a new runtime identity. Copies and reopens have no promised cross-file or cross-session object identity. Before storing references to sketch entities or model objects, the owning feature must specify persistent-ID lifecycle, edit/undo behavior, copy/fork semantics, and migration; P2-32/35 own those consumers.
5. **Version 2 is triggered by durable data not representable in the v1 command history.** The first accepted persistent sketch/profile entities, persistent feature references, or required source provenance must submit an archive schema decision before implementation. The design must identify owners and stable identifiers for those records. Required provenance should include the MyCAD release/source identity, Python implementation/version, build123d and OCP/OCCT versions, command/plugin name/version (and plugin API/package identity when applicable), units, and a versioned geometry-policy/tolerance source. Viewport mesh tolerances (`0.1 mm`, `15°`) affect tessellation only and are not model provenance; geometry-affecting tolerances must be explicit command parameters or named policy versions.
6. **Migration is explicit and non-destructive.** A future version hop must be a deterministic, pure data-to-data transform, validate the result at each hop, preserve the v1 six audit fields and amendment records, and report source and target versions. Opening a file must never overwrite it as a side effect. A migrated document is written only after an explicit save operation; the original bytes stay available until a replacement succeeds. Unknown future versions are rejected explicitly. The shipped v1 migration registry remains empty; this ADR does not add a speculative v2 schema or migration.
7. **Keep the current save/recovery target modest.** A successful same-directory `os.replace` provides atomic pathname replacement where the platform/filesystem implements that operation; it is not a backup, transaction journal, or power-loss durability guarantee. No automatic backup or crash recovery is included in this Phase 2 delivery. Write/replace failure must preserve the previous archive, leave the document dirty, omit `document_saved`, and clean up the temporary file. A stronger durability target requires a separate cross-platform decision and interruption/restart evidence; do not describe `os.replace` alone as full recovery.

## Consequences

- A static v1 fixture is retained independently of the current writer so future schema changes cannot silently make old archives unreadable.
- The existing migration package remains an unused v1 identity hook until a real next-version schema exists.
- Users should treat `.mc.json` as a portable current-history document, not as a software bill of materials or a permanent event log.
- A platform crash/power cut can still lose the most recent save even when ordinary write failures preserve the previous file.
- P2-24 closes the format and recovery decisions; implementation of sketch persistence, stable IDs, provenance fields, BREP checkpoints, and recovery journals remains explicitly gated by their owning feature/version decision.

## References

- [ADR-001](ADR-001-command-bus-and-history-replay.md) — command history and replay.
- [ADR-002](ADR-002-document-archive-format-v1.md) — frozen v1 archive.
- [ADR-003](ADR-003-extension-points-and-plugin-api-versioning.md) — plugin contract and trust boundary.
- [P2-11–19 CAD semantic loop](../../.omo/evidence/task-P2-11-19-cad-semantic-loop.md) — runtime-only identity and P2-17 profile prototype.
- [P2-24–27 phase plan](../../.omo/plans/phase2-agent-loop.md) — archive and delivery acceptance.
- [ADR-009](ADR-009-sketch-archive-v2.md) — the approved v2 trigger and sketch identity persistence contract.
