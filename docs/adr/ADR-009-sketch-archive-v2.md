# ADR-009 — Sketch command persistence and archive v2

Status: Accepted 2026-10-25

## Context

`.mc.json` v1 is a frozen command-history format. P2-32 requires sketch and entity identities to survive save, reopen, undo, redo, and replay. P2-36 will refer to a sketch from solid features. Adding those durable identities to an archive without an explicit version would violate ADR-008. Storing a second top-level sketch snapshot would also create two sources of truth beside the Bus-owned replay history.

## Decision

1. **Keep v1 unchanged.** Its exact five top-level keys and six command audit fields remain those in ADR-002. Existing v1 files continue to open and save as v1 unless a successful command requires the v2 schema. Opening a v1 file never upgrades or writes it.
2. **Use v2 for durable sketch identity.** The v2 top-level keys are `format`, `version`, `metadata`, `commands`, `named_groups`, and `provenance`. Command audit fields and optional append-only `amendments` keep their v1 wire shape. V2 requires a closed provenance object containing MyCAD release/source revision, Python implementation/version, build123d and OCP/OCCT versions, units, geometry-policy version, and the package/API identity of plugin commands present in history. New writes also include optional solver-package provenance (`planegcs`) when available; readers accept earlier v2 files that predate this field. Missing runtime facts are reported explicitly; they are not guessed.
3. **Keep replay history authoritative.** There is no separate `sketches` archive collection. Sketches and their entities are reconstructed by replaying ordinary Bus commands. Stable `sketch_id` and `entity_id` values are command parameters; references from later features use those same IDs. A command is the only model write path, and undo, redo, history edit, open, and rollback continue to use full deterministic replay. Runtime `FeatureId`, `BodyId`, and `TopologyId` remain distinct from persisted sketch/entity IDs.
4. **Release authoring commands only through their task decisions.** `sketch.create@1` retains its frozen frame-and-entity shape. The additive `sketch.create@2` schema requires a layer table and per-entity layer names, and may carry a planar `support_face` selector anchor. When attached, replay resolves that anchor against the current preceding model history and reconstructs the right-handed work-plane frame; a selector that no longer resolves fails explicitly instead of silently moving the sketch to another face. No runtime topology identity is serialized. `sketch.create@3` may carry length, point-distance, angle, radius, or diameter annotations and inferred horizontal/vertical relations on individual line entities alongside v2 sketch data. Each record stores stable geometry references and explicit source; dimensions additionally store value/unit, driving/reference state, precision, and display scale. Replay checks dimensions against geometry and checks inferred axis relations against exact line geometry; neither path invokes the optional solver. `sketch.create@3` is used for validated DXF annotation imports and auto-inferred draft relations. The interactive editor keeps the in-progress sketch as a disposable draft; Finish submits one command, while Cancel writes nothing. `sketch.constraint.add@1` stores one accepted constraint plus its solver-produced geometry state; replay does not invoke the optional solver. `sketch.constraint.add@2` adds optional dimension precision and display-scale fields without changing @1. P2-34 owns later edit/replace/delete commands. P2-36 releases `feature.extrude@2`, `feature.revolve@2`, and `feature.hole@2`; replay resolves each stable sketch ID from the preceding command history and rebuilds the solid. A sketch hole accepts only non-construction circles on the selected planar target face and uses their radii as hole diameters. The new hole version also accepts the v1 parameter shape; no v1 schema or meaning changes. No existing command version changes meaning.
5. **Upgrade on explicit model change.** A command spec declares its minimum archive schema version. The Bus raises the in-memory document schema version only after that command succeeds; failed execution and rollback leave it unchanged. Saving a v2 document transforms the v1-shaped payload to v2 with a deterministic pure data-to-data migration that receives captured provenance as input, validates each version hop, and preserves every existing audit field and amendment. The original file is replaced only after the complete v2 output has validated and the atomic write succeeds. Undo does not downgrade a document that has entered v2.
6. **Reject unsupported future data.** Readers accept v1 and v2 explicitly; unknown versions, unknown fields, malformed IDs, invalid geometry, and incomplete required provenance fail with a path-specific error. A legacy v1 archive is never reported as having persistent sketch entities. No BREP snapshot or bitwise cross-version geometry guarantee is introduced.

## Consequences

- The command history remains the single source for undo/replay, and independent 2D documents need no alternate persistence subsystem.
- New command IDs and their JSON parameter schemas must be released in ADR-003 before registration. Existing commands and v1 fixtures stay compatible.
- V2 provenance describes the environment needed to assess replay; it does not promise identical OCCT results across environments.
- P2-32 implements the v2 reader/writer migration and sketch creation command. P2-34, P2-35, and P2-36 extend the command history using the same identity and migration contract.

## References

- [ADR-001](ADR-001-command-bus-and-history-replay.md) — unique write path and full replay.
- [ADR-002](ADR-002-document-archive-format-v1.md) — frozen v1 schema and audit fields.
- [ADR-003](ADR-003-extension-points-and-plugin-api-versioning.md) — command ID/version release policy.
- [ADR-008](ADR-008-persistence-reproducibility-and-recovery.md) — v1 compatibility, provenance, and migration boundary.
- [P2-32](../../.omo/plans/phase2-agent-loop.md) — first consumer of sketch identities and archive evolution.
