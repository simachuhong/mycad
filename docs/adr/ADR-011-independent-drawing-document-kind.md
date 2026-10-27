# ADR-011 — Independent 2D drawing document kind

Status: Accepted 2026-10-25

## Context

P2-32 needs a standalone 2D drawing workflow alongside part documents. The
existing v1 archive is frozen, and v2 added provenance without a document-kind
field. Inferring a drawing from `sketch.create` would misclassify parts that
contain sketches for downstream features. Reusing the part kind would also
allow solid-modeling commands to enter a drawing history.

## Decision

1. Add archive schema v3 with one required top-level `document_type` field,
   whose only values are `part` and `drawing2d`. The remaining structure and
   provenance rules match v2. The field is archive data, never inferred from
   command history or metadata.
2. Read v1 and v2 without rewriting them; both mean `part`. V3 writes retain
   their explicit kind. Unknown kinds, extra keys, and malformed provenance
   remain hard validation errors.
3. A new `drawing2d` document starts at archive version 3. Its Bus accepts only
   the released drawing commands `sketch.create@1`–`sketch.create@3`, and
   `sketch.constraint.add@1`–`sketch.constraint.add@2`. Archive validation rejects any other command
   or 3D named groups before replay. Adding drawing commands requires an
   explicit allowlist update and tests.
4. `Document.document_type` is immutable for the lifetime of the document.
   The application factory creates either a part or a drawing, while ordinary
   open/save continues through the existing persistence path. This preserves
   the one command-history source of truth, undo/redo, replay, and atomic save.
5. The standalone drawing UI exposes sketch tools and DXF exchange. It does
   not expose solid feature commands or STEP/STL export as drawing workflows.
   Planar face-attached sketches remain a part-document workflow; their selector
   anchors are re-resolved during replay and fail explicitly when stale.

## Consequences

- Existing v1/v2 archives keep their exact wire shape and remain part documents.
- V3 adds no alternate persistence subsystem or geometry snapshot.
- Drawing archives stay within the currently released sketch command set;
  P2 G tasks govern further sketch editing and curve-repair capabilities.
- The document kind is a durable compatibility contract and may not be changed
  by a UI toggle after a document has been created.

## References

- [ADR-001](ADR-001-command-bus-and-history-replay.md) — Bus-owned writes and replay.
- [ADR-002](ADR-002-document-archive-format-v1.md) — frozen v1 contract.
- [ADR-008](ADR-008-persistence-reproducibility-and-recovery.md) — versioned migration and provenance.
- [ADR-009](ADR-009-sketch-archive-v2.md) — stable sketch identities and v2 provenance.
- [P2-32](../../.omo/plans/phase2-agent-loop.md) — independent drawing workflow.
