# P2-37 Body Operations Design

## Intent

Add Solid Edge style body-to-body Boolean operations and transformations to a part document. Commands must pass through the existing plan preview/confirm flow and remain deterministic under save, reopen, undo, redo, and history replay.

## Current constraints

- `Viewport` exposes current runtime `BodyId` values, but `BodyId` is deliberately ephemeral and cannot be serialized.
- The geometry kernel stores an aggregate `Part`; solids are available in deterministic `Part.solids()` order.
- Face and edge commands already turn picks into replayable geometric selectors and resolve them in the geometry adapter.
- A body operation must not silently fall back to a different solid when a saved reference becomes stale.

## Approaches

1. **Persist a new body UUID in every body-producing command.** This best represents feature-tree lineage, but requires versioning and migrating every existing solid-creation command before any body can be selected.
2. **Serialize runtime `BodyId`.** This is small but invalid: replay and open create new runtime identities.
3. **Use a geometric body selector.** Store volume, center of mass, bounding box, and an explicit rank for duplicate signatures; resolve against current solids with tight tolerances. This extends the existing face/edge selector model and needs no alternate history state.

## Decision

Use approach 3 for the first P2-37 body operations. Missing or ambiguous matches are hard errors. The bounded first Boolean command selects exactly one target body and one tool body, supports union, difference, and intersection, rejects empty or multi-solid operation results, and can retain the tool body as a separate solid. This does not claim persistent feature-tree lineage; if upstream edits change the selected body's geometric signature, replay stops at the stale reference for user repair.

## Follow-up scope

Use the same selector contract for body transforms and general linear/circular body patterns. A transform replaces the selected body for move/rotate/mirror; copy retains the source and adds one translated instance. A body pattern retains its seed and adds 2–64 total instances. A linear pattern uses a signed 3D step vector. A circular pattern uses a unit axis, center, total angle, and count; count includes the seed, a full turn divides by count to avoid a duplicated endpoint, and a partial arc divides by count minus one so both endpoints are included. Each operation's parameters live in its versioned command schema; runtime identities and duplicate geometry snapshots are never persisted.

## Implementation boundary for the first release

- Boolean UI selection order is target first, tool second; the current body selection order is preserved by the viewport. The command bar requires exactly two bodies for Boolean operations and exactly one for transforms/patterns.
- The command bar makes tool retention explicit. Empty Boolean output and disconnected multi-solid Boolean output fail without writing history; a valid Boolean result replaces the target, and tool consumption follows the explicit `keep_tool` value.
- Transform axes and mirror-plane normals are unit vectors. The first UI exposes the global X/Y/Z axes plus a numeric axis/plane origin; the command schema can replay arbitrary unit vectors.
- Patterns create independent bodies rather than fused solids. They do not claim assembly constraints or feature-tree pattern dependency editing.
- These operations follow Solid Edge's body selection, Boolean target/tool, transform, and pattern command concepts. They are a documented subset and require desktop workflow comparison before any parity claim.
