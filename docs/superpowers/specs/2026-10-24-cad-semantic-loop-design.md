# CAD Semantic Modeling Loop Design — P2-11 through P2-19

## Intent

Build the next usable CAD layer above the current command-history kernel: runtime identities and safe references, result validity checks, exact measurements, editable typed parameters, and an explicit plan for profiles/work planes. Start the representative-part catalog now, while keeping its full end-to-end acceptance tied to the later profile/sketch tasks it depends on.

The user requested development of Phase 2 section C. The current plan contains P2-11 through P2-17 and P2-19; it has no P2-18 entry. Keep that numbering gap and do not invent a replacement requirement.

## Goals

- Distinguish history ordinal, runtime feature identity, body identity, and face/edge reference.
- Make stale, deleted, split, merged, missing, and ambiguous references explicit; never silently substitute by rank.
- Reject invalid BREP results before Bus commit while preserving a legitimate empty result and reporting the command/check that failed.
- Provide exact BREP-backed measurement results for supported dimensions and clear unsupported-selection feedback.
- Edit normalized command parameters through the existing registry and CommandBus, with impact preview, confirmation, audit amendments, and rollback.
- Establish a 30-case representative-part catalog with support status and a testable perturbation format.
- Decide and document the work-plane/profile/dimension schema without changing `.mc.json` v1 or claiming a general constraint solver.

## Non-goals

- No persistent feature/body/topology IDs or selector wire-format changes before P2-24.
- No universal OCCT topological naming guarantee; runtime references may expire after replay.
- No automatic geometry healing, tolerance relaxation, hidden rank fallback, or mesh-derived exact dimensions.
- No general expression engine, full sketch solver, assembly model, or AI/MCP execution path.
- No claim that P2-19's final workflow passes before its P2-32–37 dependencies exist.

## Approaches

1. **Persist object IDs in v1 archives.** Rejected: it violates ADR-002's locked six-field command audit and preempts P2-24.
2. **Use geometric fingerprints or selector rank as identity.** Rejected: dimensions and topology can change; candidates can split, merge, or exchange order, causing a reference to jump silently.
3. **Use ephemeral runtime IDs plus explicit semantic references and BREP predicates.** Selected: IDs are allocated outside the archive and scoped to a live document/replay generation; a reference resolves only when its owner and post-checks identify exactly one valid candidate. Otherwise it reports missing, drifted, or ambiguous. This fits the current core/geom boundary and can evolve with later topology-history support.

## Architecture and constraints

- `mycad.core` owns immutable, backend-neutral IDs, reference descriptors, measurement/check DTOs, and error context. It must not import build123d, OCP, numpy, or Qt.
- `mycad.geom` owns BREP validity, topology evolution queries, exact measurements, and mapping to neutral DTOs.
- `mycad.app` remains the only core/geom composition root. GUI edits and any repair go through `CommandBus`; Qt widgets stay in `mycad.ui`.
- `HistoryOrdinal` is a position for navigation/edit commands; it is not a FeatureId, BodyId, or topology identity.
- A runtime identity is not serialized. Replay/rebind may invalidate topology references; a new runtime identity must never be inferred from a reused ordinal.
- Current boolean operations do not preserve OCCT subshape evolution maps. The resolver can classify stale generation/owner loss/no-match/ambiguity, but it reports multiple candidates as ambiguous instead of claiming split or merge without lineage evidence.
- Existing schema validation and normalized parameters remain the source of truth for CLI, GUI, and plan editing.
- Geometry validity is necessary, not sufficient: valid BREP, expected entity count, and design-intent measurements are separate checks.
- P2-17 is a schema/prototype/risk decision. Implementing full sketch editing and solving remains P2-32–36.

## Scope and acceptance boundaries

- P2-11–16: deliver runtime identity/reference infrastructure, checked BREP results, supported exact measurements, registry-driven edit forms, and Bus-backed history editing.
- P2-17: decide profile/work-plane/dimension representation and provide a neutral round-trip prototype with a hole profile and a non-XY plane; do not add a solver.
- P2-19: create and classify approximately 30 cases, and start parameterized regression coverage. Final end-to-end create/select/edit/measure/save/reopen/export and 100 perturbation/recovery cases remain gated on P2-32–37; do not mark P2-19 complete until those run.

## Builder decisions

- Keep runtime identity generation in the core model boundary and allocate new values rather than deriving them from ordinals.
- On successful replay, affected topology identities expire; references either resolve uniquely through explicit semantic/evolution evidence or raise a structured reference error.
- Measurement values include a unit and the source document revision; UI discards results from older revisions.
- Use existing Qt and JSON-Schema subset; no new dependencies.
- The active checkout already contains uncommitted Phase 2 foundation work that these tasks depend on. Continue in that branch/workspace; a fresh worktree from HEAD would omit those changes.

## Scope calls made from the project plan

- The 30-case catalog is a proposed 18 supported / 6 expected-rejection / 6 extension-candidate split across flange, shaft/sleeve, mounting plate, cover, and boundary cases. Each case must map to currently registered commands before it is marked supported.
- P2-14's first measurement set is deliberately narrow: volume of the active body; diameter of one cylindrical face; center distance of two circular edges; and separation of two parallel planar faces. Unsupported or insufficient selections explain the required selection. All geometry values come from BREP queries.
- P2-15 edits registered replayable modeling commands (`feature.*` and `modify.*`); it excludes document metadata and query/display actions. The pre-confirmation impact reports the selected ordinal, affected downstream command IDs/count, and proposed normalized parameter delta.
- P2-13 always checks nonempty BREP validity, nonnegative finite volume, and solid validity/count. Command contracts may require one solid for a primitive `new` operation; additive operations may yield multiple solids, and a complete cut may yield a valid empty result. No other expected dimensions/counts are guessed. Design-intent checks require an explicit parameter or measurement assertion.

These are implementation calls for the requested start, not new user requirements. If a case's command chain cannot be built with current registered commands, classify it as a rejection/extension candidate rather than as supported.
