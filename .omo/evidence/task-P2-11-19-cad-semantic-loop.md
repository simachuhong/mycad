# P2-11–19 CAD semantic loop implementation evidence

Date: 2026-10-24  
Branch: `codex/phase2-foundation`  
Workspace remains uncommitted; pre-existing P2-00–10 changes are retained.

## Scope and status

| Task | Status | Delivered scope |
|---|---|---|
| P2-11 runtime identity | Complete | Added distinct `FeatureId`, `BodyId`, `TopologyId`, and `HistoryOrdinal` value types. Runtime IDs are not serialized into archive v1. The kernel retains a body identity across consecutive single-body edits, assigns separate identities to current disconnected solids, and allocates new IDs after replay/undo/redo. |
| P2-12 semantic references | Partial | Added neutral face/edge references, exact geometric anchors, predicate resolution, generation staleness and deleted/no-match/ambiguous errors. Explicit repair is previewed in the typed edit dialog and committed through `CommandBus.edit_and_replay`, preserving the original timestamp and appending an amendment. OCCT modified/generated topology lineage is not retained, so split/merge cannot be distinguished and reports ambiguity rather than guessing. |
| P2-13 geometry validity | Complete | Added structured validity results and validation before kernel state/snapshot commit. Valid empty results are distinct from invalid non-empty topology; checks cover BREP validity, solid structure, and finite nonnegative volume without healing geometry. |
| P2-14 exact measurements | Complete | Added read-only, revision-tagged measurement DTOs and exact BREP queries for volume, cylindrical-face diameter, circular-edge center distance, and parallel-plane separation. The Measure tab exposes neutral face/edge candidates, units and source, reports unsupported/stale results, and invalidates displayed values after model changes. |
| P2-15 history edit | Complete | Added typed history editing with selected ordinal, downstream replay impact, normalized parameter delta, reason and explicit confirmation. Changes go through the serialized worker and Bus; failed replay rolls back and identifies the failing command. Successful edits preserve timestamp, append amendments, clear redo, mark the document dirty, and survive save/reopen. |
| P2-16 typed forms | Complete | Added registry/schema-driven controls and shared normalization/validation for the implemented schema subset, including lengths/angles, enums, vectors, nested values and face/edge references; integrated with plan and history editing. |
| P2-17 profile/work-plane prototype | Complete as a prototype/design decision | Added immutable neutral work-plane, contour, construction-segment, dimension-label, and profile values, with oblique right-handed frames and strict JSON-compatible round-trip. Documented persistence/replay boundaries. No solver or archive-v1 extension was introduced; implementation of sketch-driven modeling remains in P2-32–36. |
| P2-18 | Not present | No P2-18 item exists in the project plan; no scope was invented. |
| P2-19 scenarios | Partial | Catalog contains 30 cases (18 supported, 6 expected rejection, 6 extension candidates) across five categories. Added 108 linked perturb/restore records: 30 primitive cases execute now; 78 complete-chain records are gated on P2-32–37. Regression coverage includes flange create/measure/edit/undo/redo/archive reopen and STEP volume round-trip. |

## Important code and artifacts

- Core contracts: `src/mycad/core/identity.py`, `semantic_refs.py`, `measurements.py`, `geometry_checks.py`.
- BREP implementation: `src/mycad/geom/kernel.py`, `selectors.py`, `query.py`, `profiles.py`.
- UI: `src/mycad/ui/parameter_forms.py`, `right_panel.py`, `main_window.py`.
- Scenario data and tests: `examples/representative_parts.json`, `examples/parameter_perturbations.json`, `tests/scenarios/`.
- Profile design note: `docs/design/profile-workplane-dimensions.md`.
- Follow-up hardening: oneOf branch replacement removes hidden values and stale field paths; profile holes must remain strictly inside an outer contour; circular-edge target resolution filters all matching parent faces before requiring an unambiguous edge; replay errors retain command/path/reason fields; measurement UI defers kernel queries while the serialized worker is busy.
- GUI integration guard: a direct viewport refresh consumes an already scheduled coalesced refresh. The shell smoke test uses a local `QEventLoop`, so it does not stop pytest-qt's application event loop before queued worker completions.

No change was made to `src/mycad/core/schema_v1.py`; runtime IDs and profile prototypes do not alter `.mc.json` v1. No type-ignore or pyright-ignore directives were added.

## Verification evidence

The following scoped and final integration runs were completed:

- `uv run pytest tests/geom/test_body_identities.py tests/core/test_identity.py tests/geom/test_geometry_validity.py tests/geom/test_kernel_primitives.py -q` — 50 passed.
- `uv run pytest tests/geom/test_profile_workplane_prototype.py tests/geom/test_features.py -q` — 41 passed.
- `uv run pytest tests/scenarios/test_parameter_perturbations.py -q` — 33 passed.
- `uv run pytest tests/scenarios tests/geom tests/core/test_persistence.py tests/formats -q` — 255 passed (before the subsequently added body-identity test).
- Combined semantic/measurement/history/forms/profile/scenario/layering scoped run — 244 passed (before the subsequently added body-identity test).
- Focused P2-15/measurement UI run — 8 passed; broader task UI scope — 87 passed.
- Latest identity/validity/kernel primitive scope — 50 passed as listed above.
- Regression tests for branch switching, profile containment, edge target selection, Bus error context, and measurement/worker isolation — 25 passed.
- `uv run pytest tests/ui -q` — 114 passed.
- `uv run pytest -q` — 1046 passed in 131.61 s.
- `uv run ruff check src tests` — passed.
- `uv run ruff format --check src tests` — 203 files formatted.
- `uv run basedpyright src/mycad` — 0 errors, 0 warnings, 0 notes.
- `git diff --check` — passed.

An initial integration pass exposed stale async UI assertions, the intentionally expanded ADR set, an outdated UI-document hash, and branch/error-context defects; these were resolved and re-run. A later UI-order-only timeout traced to `test_shell_smoke` calling `QApplication.quit()` and leaving subsequent queued worker completions unprocessed. That test now runs its timer against a local `QEventLoop`; the full 1046-test run then passed.

## Limits and follow-up

- P2-12 requires operation-level OCCT topology evolution data before reliable split/merge lineage can be implemented.
- P2-19's 78 full-chain scenarios require the later sketch and modeling work in P2-32–37. Keep the parent task partial until those cases can execute end to end.
- Persistent semantic identity/schema decisions remain under P2-24; `.mc.json` v1 remains unchanged.
- No commit, PR, or external publication was created.
