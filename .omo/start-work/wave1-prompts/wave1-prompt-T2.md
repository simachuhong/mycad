TASK: Implement todo "T2 geom 内核适配层" (sealed build123d kernel adapter + predicate selectors + neutral DTO/query/tessellation) of the approved MyCAD Phase 0 plan. Work dir: /media/sima/Data/projects/MyCAD (Linux, Python 3.12.3 via uv — ALWAYS `uv run <cmd>`; .venv already synced, do NOT add dependencies or run uv sync/lock).

ENVIRONMENT & ORCHESTRATION RULES (non-negotiable):
- T1 (Wave 0) is complete and committed (9d99fb7). It owns three files you CONSUME, never modify, never duplicate:
  - src/mycad/core/exceptions.py — closed 15-class taxonomy (you use ValidationError, TopologyReferenceError, GeomVersionError, GeometryBuildError, EmptyGeometryError). NEVER define new exception classes anywhere.
  - src/mycad/core/geometry_types.py — MassProperties/BoundingBox/Tessellation neutral DTOs, the ONLY definitions (geom imports them one-way: geom→core).
  - src/mycad/core/selectors.py — FaceSelector/EdgeSelector frozen dataclasses, the ONLY definitions (you may re-export from mycad.geom.selectors for import-path convenience; never redefine).
- PARALLEL SIBLINGS: two other agents work concurrently in this same tree on disjoint paths (T3: src/mycad/commands/**, tests/commands/**; T4: docs/adr/**, tests/test_adr_docs.py). NEVER touch paths outside YOUR SCOPE below. NEVER run bare full-suite commands (`uv run pytest -q` without paths, bare `uv run basedpyright`, `uv run ruff check .`) — siblings' in-progress files would falsely break them. Use ONLY the path-scoped verification commands in this prompt.
- NEVER run git add/commit/stash/push/checkout — the orchestrator commits after integration. NEVER edit .omo/plans/phase0-mvp.md, .omo/boulder.json, or any docs/ file.
- Quality discipline (guard-test enforced): every .py file starts EXACTLY with two lines `# SPDX-FileCopyrightText: 2026 MyCAD contributors` then `# SPDX-License-Identifier: Apache-2.0`; basedpyright strict zero errors, zero `# type: ignore`/`# pyright: ignore`, zero `Any` escapes (do NOT create tests/typing/); ruff select E,F,I,N,UP,B,SIM,RET,PT,PL, line-length 100, target py312.
- If blocked by anything outside your scope, STOP and report `BLOCKED: <reason>` with full detail instead of fixing it yourself.

AUTHORITATIVE SPEC — READ THESE FIRST, IN FULL, before writing any code:
1. .omo/plans/phase0-mvp.md lines 191–221: your todo (module layout, BuildKernel surface, the 6 written FaceSelector resolution rules, test matrix ①–⑩, version-gate monkeypatch discipline, layering-guard whitelist rules).
2. Same file lines 26–58 (scope + guardrails) and 75–91 (verification strategy).
3. Same file lines 550–662: Appendix A.0/A.1/A.2 — authoritative JSON field shapes (FaceSelector/EdgeSelector descriptors; feature.box params size_x/size_y/size_z/center/mode; feature.cylinder params radius/height/center/mode).
4. src/mycad/core/{exceptions,geometry_types,selectors}.py (T1 deliverables).
5. .omo/evidence/spike/flange_spike.py and .omo/evidence/spike/fillet_probe.py — PROVEN build123d 0.11.1 idioms (BuildPart builder, Cylinder(10,20,mode=Mode.SUBTRACT) volumes verified analytically: π·8·(40²−10²)=37699.111843…; Box(5,5,30,mode=Mode.SUBTRACT) from 20³ cuts 3750). These repo copies are authoritative; ignore any /tmp paths mentioned in the plan.
6. .omo/drafts/phase0-mvp-research-ledger.md — §2 environment, A2/A3/A6/A9, E1/E4/E11, R2/R3/R14/R15.
7. docs/技术路线.md:55-63 and docs/需求分析书.md:80-88 (F-MOD-01).

YOUR SCOPE (create/modify ONLY these paths):
- CREATE: src/mycad/geom/ package (suggested kernel.py, selectors.py, query.py + any internal split you find useful e.g. _b123_ops.py — internal layout is your call, the layering guard judges by package boundary).
- CREATE: tests/geom/ test package.
- MODIFY: tests/test_layering.py — extend the AST whitelist additively: allow build123d/OCP/numpy imports ONLY in src/mycad/geom/, tests/geom/, and tests/helpers/step_roundtrip.py (a T8 test helper that does NOT exist yet — the spec's exact whitelist wording includes it). Read the current test first; keep every existing assertion passing. Do NOT create tests/helpers/.

EXPECTED OUTCOME (deliverables + success criteria):
- All SCOPED VERIFICATION commands exit 0; the spec's test matrix fully implemented and green; evidence file written; DoneClaim produced.

MUST DO (exhaustive requirements from the spec):
- src/mycad/geom/kernel.py: version gate at import via importlib.metadata.version("build123d") parsed to int tuple vs (0, 11, 1); parse failure or mismatch → GeomVersionError containing actual AND expected. NO `packaging` dependency. Structure the gate as a directly-testable callable (e.g. _assert_b123d_version()) so tests can monkeypatch importlib.metadata.version — QA discipline FORBIDS monkeypatching build123d.__version__ (the implementation must not read it).
- class BuildKernel: reset() -> None; apply(command_id: str, params: Mapping[str, object]) -> None; mass_properties() -> MassProperties; tessellate(linear_tolerance_mm: float, angular_tolerance_deg: float) -> Tessellation. THIS TODO fully implements feature.box AND feature.cylinder in ALL THREE modes (new/add/cut via build123d Mode.NEW/ADD/SUBTRACT — mode=cut for these two commands belongs to T2, NOT T5). export_step/export_stl: placeholder method signatures raising NotImplementedError (T8 wires them later). NO import_step, NO file-reading public method, NO build123d Part object ever leaving the geom package.
- FaceSelector resolution in src/mycad/geom/selectors.py — implement the spec's 6 rules verbatim: (1) filter plane→planar faces (axis=outward normal), cylinder→cylindrical faces (axis=center axis, UNDIRECTED: +Z matches −Z, but +X never matches a Z-axis cylinder); (2) plane REQUIRES axis (None → ValidationError, message says plane normal must be explicit); cylinder axis optional (None=all cylindrical faces); (3) deterministic total order: Face.area descending, ties by face-center lexicographic (x, then y, then z) ascending, plain float compare, NO tolerance merging — build123d group_by/sort_by are implementation means, the final total order must equal this rule (dedicated tiebreak test with two equal-area faces); (4) rank given → 0-based index into sorted candidates, rank ≥ candidate count → TopologyReferenceError with candidate count AND requested rank in reason; rank omitted → exactly 1 candidate required else TopologyReferenceError (reason "no-match"/"ambiguous" + counts; NEVER silently take candidate 0); (5) surface/axis mismatch → TopologyReferenceError reason="no-match" with descriptor_json echoed; (6) EdgeSelector: resolve ALL parent_faces first (any failure → TopologyReferenceError), order-preserving dedup union of their edges, curve filter line/circle (empty after filter → TopologyReferenceError), same total-order semantics (edge length descending + midpoint lexicographic). Failure messages include command_id and the descriptor JSON.
- geom receives ONLY already-normalized descriptors (use `.get("axis") is None` checks; the ""→key-deletion normalization happens upstream in T3 — geom never sees ""). Resolution goes through build123d algebraic selectors (.faces().filter_by(GeomType...), normal filtering, group_by(Face.area)[-1].sort_by(Axis.X)[-1] idioms).
- src/mycad/geom/query.py: mass_properties() fills the core MassProperties DTO with EXPLICIT float()/tuple() conversions (numpy types never cross the geom boundary). Empty-geometry semantics: after reset/no solid → solid_count=0, volume=0.0, bbox=None, center_of_mass=(0.0,0.0,0.0) — NOT an exception. tessellate(): memory-only data (vertices/triangle_indices as tuples of floats/ints); writes NO file format, touches NO OpenGL/rendering.
- Conventions (docstrings): units mm, decimal degrees; Cylinder centered at origin spanning z∈[-h/2,+h/2]; boolean mode enum new|add|cut.
- Consume core exceptions only; geom→core one-way imports; core never imports geom.

TESTS (tests/geom/) — the spec's matrix ①–⑩ is MANDATORY, at minimum:
- Three-mode volumes vs formulas computed IN THE TEST: box 80*80*8=51200; cylinder math.pi*(40**2)*8; flange cut-form math.pi*8*(40**2-10**2-4*3**2) with tolerance 1e-6 mm³ (NEVER hand-type rounded constants like 36794.3332, NEVER reverse-record from implementation output).
- Selector matrix: (plane,+Z) rank=0 selects the largest flange face; the TWO-BLOCK stacked construction (e.g. Box(10,10,10,align=(MIN,MIN,MIN)) + Box(20,20,5,align=(MIN,MIN,MIN)) or equivalent — comment explains "two +Z outward horizontal faces with different areas") giving exactly 2 candidates where omitted rank → TopologyReferenceError(ambiguous) — do NOT use a single cube for ambiguity; rank=1 takes the second-largest; rank=99 → TopologyReferenceError with candidate count in reason; (cylinder,None) selects all 6 cylindrical faces of the flange; (cylinder,+Z) and (cylinder,−Z) yield the same result on Z-axis cylinders (undirected); (cylinder,+X) on Z-axis cylinders → no-match; plane with axis omitted (None and "" inputs) → ValidationError; "" and None behave identically (isomorphic assertion); equal-area dictionary-order tiebreak picks smaller (x,y,z); EdgeSelector parent-mismatch and curve-filter-empty → TopologyReferenceError (message contains command id + descriptor JSON); tessellation chord tolerance halved → triangle count strictly increases and all vertices within bbox.
- GeomVersionError: monkeypatch importlib.metadata.version → "9.9.9" (mismatch) and "0.11" (unparseable) both raise, message contains both actual and expected versions.
- Layering guard: the updated tests/test_layering.py must go RED when a forbidden import is temporarily added to core/ (e.g. `from build123d import Cylinder`), and green after restore — prove it and capture in evidence.

PROCESS DISCIPLINE (TDD): write failing tests first, then implement. Baseline first: run `uv run pytest tests/test_layering.py -q` before any change to confirm green.

API EXPLORATION (mandatory): verify EVERY build123d API call against installed 0.11.1 via `uv run python -c` probes (inspect.signature, dir(), tiny geometry prints) — NEVER write selector/builder API from memory. Spike files are proven starting points.

SCOPED VERIFICATION (all must exit 0 — use EXACTLY these path-scoped forms):
- uv run ruff check src/mycad/geom tests/geom tests/test_layering.py
- uv run ruff format --check src/mycad/geom tests/geom tests/test_layering.py
- uv run basedpyright src/mycad/geom tests/geom tests/test_layering.py
- uv run pytest tests/geom tests/test_layering.py -q
- Final no-regression check: uv run pytest tests/core tests/test_smoke.py tests/test_spdx.py -q

MANUAL-QA CHANNEL (real-surface proof — capture FULL output into evidence):
- `uv run python -c "..."`: build the flange via your kernel following the spike's proven construction — feature.cylinder radius=40 height=8 mode=new; feature.cylinder radius=10 height=20 mode=cut (through); 4× feature.cylinder radius=3 height=20 mode=cut at center (±25,0,0),(0,±25,0) (PCD50); print mass_properties (volume vs math.pi*8*(40**2-10**2-4*3**2), solid_count, cylindrical_face_count==6, bbox 80×80×8); then a (plane,+Z) rank=0 resolution and a (cylinder,None) face count. Include the tessellation monotonicity numbers (triangle counts at two tolerances).

EVIDENCE: write .omo/evidence/task-2-phase0-mvp.md (format reference: .omo/evidence/task-1-phase0-mvp.md): commands, key outputs, volume table, failure-scenario tamper proofs (layering red→restore→green; rank=99; version-gate monkeypatch), deviations with justification (none expected), UTC timestamps. Record adversarial classes: malformed_input (bad descriptors: rank=99/no-match/ambiguous — probed), flaky_tests (formula-based expectations + explicit tolerances — probed), misleading_success_output (volumes asserted against math formulas not implementation echoes; version gate actually trips — probed), stale_state (reset()→empty semantics — probed); prompt_injection/cancel_resume/hung_commands/repeated_interruptions n/a one-liners; dirty_worktree integration-owned.

MUST NOT DO: no extrude/revolve/hole/hole_pattern/fillet/boolean_cut (T5); no STEP/STL implementation (Protocol placeholders only); no silent exception swallowing; no second OCCT binding; no numpy/OCCT types in DTOs; no tessellation file formats or OpenGL; no modifications outside YOUR SCOPE; no git operations; no new dependencies; no full-suite commands; no new exception classes; no redefinition of core DTOs/selectors.

FINAL REPORT — end your final message with a fenced ```json block containing exactly:
{"DoneClaim":{"task":"T2 geom kernel adapter","changed_files":["..."],"tests":["<exact command> -> <result>"],"manual_qa":[".omo/evidence/task-2-phase0-mvp.md"],"cleanup":["<receipt: temp files removed, no processes left running>"],"risks":["known risk or none"]}}
<!-- OMO_INTERNAL_INITIATOR -->