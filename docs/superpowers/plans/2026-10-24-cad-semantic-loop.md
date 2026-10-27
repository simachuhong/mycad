# CAD Semantic Modeling Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the implementable P2-11–17 foundations plus the P2-19 scenario catalog without changing archive v1 or claiming acceptance that depends on later P2-32–37 work.

**Architecture:** Keep IDs, semantic references, result checks, and measurement DTOs in core; keep all BREP operations in geom; compose through `app.py`; display and edit in UI, with all history changes submitted through CommandBus. Runtime IDs are ephemeral and separate from history ordinals and persistent selectors.

**Tech Stack:** Python 3.12, build123d 0.11.1 / OCP 7.9.3.1.1, PySide6, pytest, ruff, basedpyright.

**Spec:** `docs/superpowers/specs/2026-10-24-cad-semantic-loop-design.md`

## Global Constraints

- Core cannot import build123d/OCP/numpy; geom is the only CAD-backend adapter; UI is the only PySide6 layer; `app.py` is the core/geom bridge.
- Every document mutation goes through CommandBus; edits preserve original audit timestamps and append amendments.
- `.mc.json` v1 and its six audit fields remain unchanged; do not persist new runtime IDs or new reference forms before P2-24.
- `rank` remains an ordered query index, never an identity fallback.
- Invalid geometry is rejected before commit; empty results remain valid; no automatic healing or tolerance relaxation.
- New source files carry the required SPDX headers; no type-ignore suppressions or per-file lint exemptions.
- Preserve current uncommitted workspace state; do not commit or publish.

## Review Focus

- Undo/redo, parameter edits, and replay must not revive an expired face/edge reference under a reused ordinal.
- Split/merge and multiple geometric matches must fail with command/parameter location, not pick the first candidate.
- Empty geometry and valid multi-solid geometry must not be conflated with invalid BREP.
- Measurement results must use exact BREP values and must be invalidated on document revision changes.
- GUI parameter editing must not bypass registry validation, confirmation, Bus rollback, or plan invalidation.
- Old `.mc.json` fixtures must still load byte-contract-compatible schema v1 data.

---

### Task 1: P2-19 representative-part catalog (initial deliverable)

**Files:** Create `examples/representative_parts.json`; create `tests/scenarios/test_representative_parts.py`; add an examples package/readme only if the repository convention requires it.

**Interfaces:** Each record has `id`, `name`, `category`, `status` (`supported`, `expected_rejection`, `extension_candidate`), `commands`, and a short acceptance note. Target the design's 18/6/6 status split across the five named categories; unsupported cases are explicit rather than represented as passing capabilities.

- [x] Write tests for unique stable IDs, all three status classes, approximately 30 cases, valid command IDs, and valid status values.
- [x] Run `uv run pytest tests/scenarios/test_representative_parts.py -q`; expected initial failure because catalog is absent.
- [x] Add and classify the representative cases across flange, shaft/sleeve, mounting plate, cover, and boundary cases.
- [x] Re-run the catalog test and `uv run ruff check tests/scenarios/test_representative_parts.py`.

### Task 2: P2-11 runtime identity DTOs and lifecycle prototype

**Files:** Create `src/mycad/core/identity.py`; modify `src/mycad/core/__init__.py` only for intended exports; test `tests/core/test_identity.py`.

**Interfaces:** `FeatureId`, `BodyId`, `TopologyId`, and `HistoryOrdinal` are frozen distinct value types. `RuntimeIdentityScope.new_feature_id()`, `new_body_id()`, and `new_topology_id()` allocate opaque runtime IDs; `invalidate_topology()` expires references without reusing IDs. No persistent archive fields are added.

- [x] Write tests for type distinction, monotonic invalidation, unique IDs across undo/redo-like replay generations, and stale topology rejection.
- [x] Run the new test and confirm it fails because the API is absent.
- [x] Implement neutral identity types and a small allocator/scope without importing CAD or UI modules.
- [x] Run `uv run pytest tests/core/test_identity.py tests/core/test_selectors.py tests/test_layering.py -q`.

### Task 3: P2-13 structured geometry validity contract

**Files:** Create `src/mycad/core/geometry_checks.py`; modify `src/mycad/geom/query.py`, `src/mycad/geom/_b123_ops.py`, `src/mycad/geom/_b123_features.py`, and kernel apply/replay boundary; test `tests/geom/test_geometry_validity.py` and relevant core Bus cases.

**Interfaces:** `GeometryCheckIssue(code, message, command_id, parameter_path)` and `GeometryCheckResult(is_valid, solid_count, volume_mm3, issues)` are backend-neutral. `validate_result(part, command_id, mode)` in geom treats empty as valid for cut results, checks non-empty BREP/solid validity and finite nonnegative volume, and requires one solid only for a primitive `new` contract. Add operations may validly yield multiple solids. Invalid results raise the existing structured geometry exception before a Bus commit.

- [x] Add failing tests for valid empty, valid single solid, valid multiple solids, invalid BREP, and error command/check context.
- [x] Run the new geometry tests and observe expected API/behavior failures.
- [x] Implement BRepCheck-based validity and a single validation boundary; do not heal or modify the shape.
- [x] Add parameterized near-tangent, coplanar, thin-wall, tiny-feature, and complete-cut cases with explicit expected valid/rejected outcomes.
- [x] Run `uv run pytest tests/geom/test_geometry_validity.py tests/geom/test_features.py tests/core/test_bus.py -q`.

### Task 4: P2-12 semantic references and drift errors

**Files:** Create `src/mycad/core/semantic_refs.py`; modify `src/mycad/core/exceptions.py`, `src/mycad/geom/selectors.py`, geometry state bookkeeping, and targeted command validation; test `tests/core/test_semantic_refs.py` and `tests/geom/test_semantic_selectors.py`.

**Interfaces:** A runtime `SemanticFaceRef`/`SemanticEdgeRef` combines owner `FeatureId`, semantic role, a coarse predicate descriptor, and runtime topology generation. `resolve_semantic_face/edge` returns exactly one candidate plus validation evidence or raises a structured `TopologyReferenceError` with reason `no-match`, `drift`, `deleted`, `split`, `merged`, or `ambiguous`, including command ID and parameter path.

- [x] Write failing tests for size-driven `max_face` re-query, stable-object deletion, split/merge ambiguity, stale generation, and preservation of legacy `rank` ordering.
- [x] Verify failures are caused by missing semantic-reference behavior.
- [x] Implement only the topology-evolution evidence the current kernel can reliably provide; otherwise fail explicitly rather than infer identity from proximity or rank.
- [x] Ensure any explicit reference repair uses `CommandBus.edit_and_replay` and appends an amendment.
- [x] Run `uv run pytest tests/core/test_semantic_refs.py tests/geom/test_semantic_selectors.py tests/geom/test_face_selectors.py tests/geom/test_edge_selectors.py -q`.

### Task 5: P2-16 schema-driven typed parameter form primitives

**Files:** Create `src/mycad/ui/parameter_forms.py`; modify `src/mycad/commands/spec.py` only if the existing schema contract needs metadata; test `tests/ui/test_parameter_forms.py` and registry/validation equivalence tests.

**Interfaces:** `ParameterForm(spec, values, registry)` renders supported JSON-Schema scalar, enum, vector, nested object, face/edge reference, radius/diameter, and coordinate fields. `normalized_params()` returns JSON-compatible values validated by the existing `validate_params`; no second validation rules are introduced.

- [x] Write failing widget tests for each supported field class, invalid location, unit labels, and round-trip normalization against CLI/plan parsing.
- [x] Run the new UI test file and verify the missing form API causes failure.
- [x] Implement the minimal typed widget mapping, nested form groups, field-local errors, and selector-fill seam.
- [x] Run `uv run pytest tests/ui/test_parameter_forms.py tests/commands/test_validation.py tests/ui/test_plan_confirm.py -q`.

### Task 6: P2-14 exact measurements and revision-safe results

**Files:** Create `src/mycad/core/measurements.py`; modify `src/mycad/core/kernel_protocol.py`, `src/mycad/geom/query.py`, `src/mycad/geom/kernel.py`, `src/mycad/app.py`, and `src/mycad/ui/right_panel.py`; test `tests/geom/test_measurements.py`, `tests/core/test_measurements.py`, and `tests/ui/test_measurements.py`.

**Interfaces:** `MeasurementRequest(kind, references, revision)` and `MeasurementResult(value, unit, revision, description)` remain neutral. `BuildKernel.measure(request)` supports active-body volume, one cylindrical-face diameter, center distance between two circular edges, and separation of two parallel planar faces; unsupported/ambiguous selection returns a structured message, not a mesh estimate. UI displays only results matching the bound document revision.

- [x] Write failing analytical tests for flange hole diameter, PCD/pitch, thickness, distance, volume, unsupported references, and stale results after edit/undo/rebind.
- [x] Run tests and verify the measurement DTO and API are missing.
- [x] Implement exact BREP queries and app composition; do not introduce geometry access in core/UI.
- [x] Enable the Measure tab and show units, source, and applicability/error state.
- [x] Run `uv run pytest tests/core/test_measurements.py tests/geom/test_measurements.py tests/ui/test_measurements.py tests/test_layering.py -q`.

### Task 7: P2-15 Bus-backed history edit workflow

**Files:** Modify `src/mycad/ui/right_panel.py`, `src/mycad/ui/main_window.py`, and the execution/parameter-form integration; test `tests/ui/test_history_edit.py` and extend `tests/core/test_bus.py` only for uncovered audit behavior.

**Interfaces:** Selected replayable history feature (`feature.*` or `modify.*`) exposes its ordinal as navigation identity and parameters from the current `ExecutedCommand`. The edit dialog reports the selected ordinal, downstream command IDs/count, and proposed normalized parameter delta, then calls the existing `CommandBus.edit_and_replay(ordinal, params, actor, reason)` only after explicit confirmation. Metadata and read-only queries are outside this editor.

- [x] Write failing tests for successful upstream edit, downstream replay extent, no-op edit rejection/confirmation behavior, failed replay rollback and error location, original timestamp preservation, amendment append, redo clearing, dirty state, save/reopen, and measurement refresh.
- [x] Run the test and confirm current UI does not provide the workflow.
- [x] Implement selected-feature parameter form, impact summary, confirmation, and serialized worker dispatch; keep all writes in Bus.
- [x] Run `uv run pytest tests/ui/test_history_edit.py tests/core/test_bus.py tests/core/test_persistence.py tests/ui/test_measurements.py -q`.

### Task 8: P2-17 profile/work-plane/dimension schema decision and prototype

**Files:** Create `docs/design/profile-workplane-dimensions.md`; modify `src/mycad/geom/profiles.py` only for neutral wire prototype values; test `tests/geom/test_profile_workplane_prototype.py`.

**Interfaces:** The prototype defines a right-handed local plane frame in millimetres, closed contour values, construction geometry, and driven/reference dimension labels; 2D editor entities are distinct from 3D model entities. No solver, command namespace, or v1 persistence change is introduced.

- [x] Write failing round-trip tests for a holed profile and an oblique work plane plus invalid frame/contour cases.
- [x] Verify the current XY-only profile API fails these tests.
- [x] Implement neutral immutable prototype DTOs and the explicit design record, including external projection reference lifecycle and P2-24 storage questions.
- [x] Run `uv run pytest tests/geom/test_profile_workplane_prototype.py tests/geom/test_features.py -q`.

### Task 9: P2-19 perturbation/regression harness and status

**Files:** Extend `examples/representative_parts.json`; create `tests/scenarios/test_parameter_perturbations.py` and `tests/scenarios/README.md`; update `.omo/evidence/task-P2-19-cad-semantic-loop.md` and the OMO task only to the evidence-backed state.

**Interfaces:** Each perturbation case identifies a catalog case, parameter path, baseline value, perturbation, expected geometry/measurement/reference outcome, and restore action. Current implementation must provide at least 100 deterministic cases; deferred end-to-end fields are explicitly marked gated by P2-32–37.

- [x] Add failing discovery/count/uniqueness tests for 100 explicit expected perturbation/restore cases and required supported/reject/extension classifications.
- [x] Add executable checks for the currently supported subset; keep future profile/sketch cases as gated records, not skipped tests pretending to pass.
- [x] Implement scenario generation/fixtures and run representative create, edit, measure, undo/redo, archive, and STEP round-trip checks where supported.
- [ ] Run `uv run pytest tests/scenarios tests/geom tests/core/test_persistence.py tests/formats -q` and record duration/result.
- [x] Mark P2-19 as partial until P2-32–37 allow the full end-to-end acceptance; do not check its completion box prematurely.

## Final verification

- [ ] Run scoped Ruff check/format and basedpyright over every changed source path.
- [ ] Run the scoped test commands above and `tests/test_layering.py`.
- [ ] Confirm no archive-v1/schema or type-ignore changes; validate all catalog and scenario references.
- [ ] Fresh review; record results and the final P2 task states in `.omo/evidence/` and `.omo/start-work/ledger.jsonl`.
