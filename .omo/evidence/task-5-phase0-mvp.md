# Phase 0 / T5 evidence — geom feature layer (Wave 2)

**Task**: T5 — feature layer on BuildKernel: profiles.py, feature.extrude /
revolve / hole / hole_pattern, modify.fillet / boolean_cut, wiring in
kernel.py, tests/geom/test_features.py.
**Plan**: `.omo/plans/phase0-mvp.md` T5 section; polar frame frozen at
#round7-3 (global XY angles, start=0 → +X, CCW toward +Y, −Z not mirrored).
**UTC timestamp**: 2026-10-05T01:18:49Z (finisher pass; original delivery by a
prior agent that died at 125/128 before gates/evidence, finished per the
re-diagnosis below).
**Environment**: Linux x86_64, Python 3.12.3, uv, build123d 0.11.1, pytest 9.1.1.

## 0. Finisher re-diagnosis (this session)

The prior agent delivered all T5 code with `3 failed, 125 passed` and died
before gates and evidence. Fresh diagnosis of the 3 hole_pattern failures:

- **The implementation was already spec-correct.** Instrumented run
  (monkeypatched `_hole_cutter` spy) proves the cutter axes land at exactly
  `face_center + (R·cosθ, R·sinθ)` per the frozen #round7-3 formula —
  e.g. start=0/count=3/R=30 → axes at (30, 0), (−15, ±25.98); the volume
  assertion `100·100·5 − 3π·5²·5 = 48821.9027549038…` holds; the plate
  bbox/COM are unchanged. No change to `_b123_features.py` angle math was
  needed (the finisher prompt's presumption of an angle-computation bug was
  outdated).
- **Failure cause 1 — test measurement artifact**: `_cylindrical_face_centers`
  used `Face.center()`, which defaults to `CenterOf.GEOMETRY`; build123d
  defines that for non-planar faces as the *parametric midpoint on the
  surface* — for a full cylinder band a point one hole-radius off the axis
  (opposite the seam), NOT the hole center. Empirical proof:
  `Part() + Cylinder(5, 10)` curved face `center()` = (−5, 6.12e−16, 0).
  Fixed in-test to `face.center(CenterOf.MASS)` (area centroid of a full
  360° band lies exactly on the hole axis) — measures the quantity the spec
  defines, and is orientation-safe for −Z faces too.
- **Failure cause 2 — pytest 9 nested-approx**: `list_of_tuples ==
  approx(list_of_tuples)` is structurally always-False (pytest 9.1.1 approx
  does not nest; reports "Max absolute difference: -inf"). Fixed with the
  documented pattern `== [pytest.approx(p, abs=1e-6) for p in expected]`
  (value and length mismatches both still rejected — verified).
- **Failure cause 3 — genuine test math typo** (whitelist clause: reported
  here and in DoneClaim): in `test_hole_pattern_start_angle_90_…`,
  `x = 30·cos(2π/3) = −15` put the expected off-axis holes at (±15, −15) —
  radius 21.2, not even on the R=30 bolt circle; the frozen formula gives
  210°/330° → (∓25.98, −15). Copy-paste from the (correct) start=0 test.
  Fixed to `x = 30·cos(π/6)`; expected set now matches the spec formula
  exactly and the list is properly sorted.

## 1. Component inventory (delivered code)

| File (lines) | Contents |
|---|---|
| `src/mycad/geom/profiles.py` (107) | frozen dataclasses `Profile(ABC)` / `CircleProfile(radius, center)` / `RectProfile(width, height, center)`; `profile_from_mapping` parses the appendix-A.0 wire descriptor (unknown keys / non-positive numbers / bad centers → ValidationError); XY plane z=0, rotated datums reserved for Phase 1 |
| `src/mycad/geom/_b123_features.py` (537) | `apply_feature` dispatch + implementations: `feature.extrude` (profile × distance, signed, mode new/add/cut), `feature.revolve` (axis X/Y or unit vector — non-unit `(1,1,0)`/`(0,0,0)` → ValidationError with measured norm, never auto-normalized; angle ∈ (0, 360]), `feature.hole` (FaceSelector plane target, position center only, through_all spans bbox both ways along outward normal / blind into material with 0.01 mm overshoot), `feature.hole_pattern` (#round7-3 polar only: horizontal-plane gate `pattern-target-not-horizontal` at \|n·ẑ\| < 1−1e-9, global-XY angles, −Z not mirrored, per-instance axis = base face outward normal; kind=linear rejected explicitly), `modify.fillet` (method-form `part.fillet(radius, edge_list)`, radius-first; OCCT failure → GeometryBuildError), `modify.boolean_cut` (inline box/cylinder tool, only cut-verb user); OCCT exceptions wrapped, no OCP text crosses the boundary |
| `src/mycad/geom/kernel.py` (155, +11 wiring) | `apply` routes `feature.box`/`feature.cylinder` → T2 `apply_primitive`, everything else → `apply_feature`; docstring updated |
| `tests/geom/test_features.py` (480, 38 tests) | analytic volumes (πr²h, w·h·d, revolve shells), signed extrude, axis-norm validation matrix, hole through_all/blind/blind-on-−Z (π·2²·5 removal each), target-not-plane, predicate-mismatch TopologyReferenceError with command id, spike-flange golden via predicate path (volume 36794.3331588437…, bbox (80,80,8), 6 cylindrical faces, command-id scan: no cut-mode cylinder / no boolean_cut), fillet volume delta + oversized-radius GeometryBuildError, boolean_cut box−cylinder analytic, hole_pattern polar center assertions (+Z start 0/90, count=4 bolt circle), pattern-target-not-horizontal, kind=linear rejection |

All OCCT interaction stays inside `mycad.geom`; `tests/geom/` may import
build123d per the layering guard (whitelisted prefix).

## 2. Scoped verification (2026-10-05T01:18:49Z)

```
uv run pytest tests/geom/ tests/test_layering.py -q
  -> 128 passed in 16.04s                    (target met: 128/128)
uv run ruff check src/mycad/geom tests/geom
  -> 1 error: B024 profiles.py:23 (Profile(ABC) has no abstract members)
uv run ruff format --check src/mycad/geom tests/geom
  -> 1 file would be reformatted: profiles.py:90
uv run basedpyright src/mycad/geom tests/geom
  -> 69 errors, 0 warnings (54 in _b123_features.py, 15 in profiles.py;
     tests/geom: 0 errors, 0 warnings, 0 notes)
```

The three non-pytest gates are **inherited debt, not introduced by this
session**: the prior agent died before ever running checklist step 10 (the
scoped gates). This session's own edits are gate-clean (tests/geom pyright 0;
`_b123_features.py` and `test_features.py` formatted in-scope this session).
Full remediation is impossible within the finisher whitelist:
`profiles.py` is explicitly out of scope ("禁止改动其他任何文件"), so even a
typing pass over `_b123_features.py` (54 errors, in-scope but a frozen-design
redesign, forbidden here) could not bring pyright to 0. Quantified for the
orchestrator: B024 fix = one abstract member or ABC removal; format = one
`ruff format` pass; pyright = isinstance-narrowing Unknown leakage through
`Mapping[str, object]` parses (same class T3's closer fixed in commands/,
see task-3 evidence §5).

## 3. Tamper proof (red → restore → green)

Target: the #round7-3 polar offsets in `src/mycad/geom/_b123_features.py`
(`radius * math.cos(...), radius * math.sin(...)`). Tamper: cos/sin swapped.

```
uv run pytest tests/geom/test_features.py -q -k hole_pattern   (tampered)
  -> FAILED test_hole_pattern_plus_z_centers_follow_global_polar_angles
  -> FAILED test_hole_pattern_start_angle_90_puts_first_hole_on_plus_y
  -> FAILED test_hole_pattern_count4_centers_match_flange_bolt_circle
  -> 3 failed, 35 deselected in 8.00s
```

Restored (exact inverse edit), then:

```
uv run pytest tests/geom/ tests/test_layering.py -q             (restored)
  -> 128 passed in 16.11s
```

Red→green closed: the three polar-angle tests are load-bearing — they detect
a cos/sin swap even though every volume/golden assertion is
shift-invariant. (Note: after the probe, both in-whitelist files were run
through `ruff format`; 128 passed re-confirmed afterward.)

## 4. Inheritance & what this session changed

Prior agent (95%): profiles.py, _b123_features.py, test_features.py,
kernel.py wiring — delivered at 3 failed / 125 passed, then died; no
evidence, no gates run. This finisher session changed exactly:

- `tests/geom/test_features.py` — (a) `_cylindrical_face_centers` now uses
  `face.center(CenterOf.MASS)` + explanatory docstring (measurement artifact,
  §0 cause 1); (b) the 3 assertions use `[pytest.approx(p) for p in
  expected]` (pytest 9 nested-approx, §0 cause 2); (c) start-angle-90 test
  `x` formula `cos(2π/3)` → `cos(π/6)` (genuine spec typo, §0 cause 3);
  (d) `from build123d import CenterOf` (layering-whitelisted in tests/geom);
  (e) ruff format pass. Expected values otherwise untouched — the spec
  positions were already correctly encoded in tests 1 and 3.
- `src/mycad/geom/_b123_features.py` — tamper probe + restore (byte-equal
  semantics) + ruff format pass. No logic change: the angle computation was
  already the frozen spec.
- `.omo/evidence/task-5-phase0-mvp.md` — this file.

## 5. Adversarial classes

- **misleading_success_output** — the spy run (§0) distinguished "geometry
  correct, measurement wrong" from "geometry wrong": cutter axes, plate
  bbox, COM, and analytic volume all cross-checked before touching any test.
- **flaky_tests** — n/a: analytic volumes with 1e-6 tolerance; polar centers
  with 1e-6 abs; no timing, no network.
- **vacuous_tests** — §3 tamper probe; plus the nested-approx defect meant
  the 3 assertions could NEVER pass for any implementation — now they
  discriminate (value/length mismatches rejected, verified in §0 cause 2).
- **stale_state** — n/a: fresh BuildKernel per test; monkeypatch spy existed
  only in a /tmp script, never in the repo.
- **dirty_worktree** — no git operations (forbidden); deliverables are
  untracked Wave-2 files plus the prior agent's uncommitted kernel.py wiring.

## 6. Risks & leftovers

1. **Pre-existing gate debt in predecessor files** (§2): B024 + format in
   `profiles.py`, 69 pyright errors (54 + 15). Out of finisher whitelist;
   needs an orchestrator-dispatched follow-up or integration-time fix.
2. **No −Z-face polar center-coordinate test exists** — the T5 spec asked
   for +Z/−Z center assertions; the predecessor wrote only +Z ones (−Z
   semantics are covered indirectly via the blind-hole-on-−Z volume test and
   the horizontal-plane gate). The `CenterOf.MASS` helper is −Z-safe, so
   adding that test later is trivial.
3. **pytest 9.1.1 approx nesting** — any future nested-sequence assertion
   must use the `[approx(p) for p in expected]` pattern; worth a lint hint
   or convention note when the test suite grows.
4. `Profile(ABC)` with no abstract members is a marker base; if B024 is fixed
   by adding an abstract member, `profile_from_mapping` return-type
   narrowing stays unaffected.

## 7. Cleanup session (lint + pyright zeroing)

Scope: mechanical quality gates only (B024 + ruff format + basedpyright
strict), design frozen; whitelist = profiles.py / _b123_features.py /
kernel.py (signatures only) / test annotations. No test assertion touched.

### Error trajectory (basedpyright strict, scoped)

**69 → 54 → 39 → 29 → 15 → 6** (ruff 1 → 0; format 1 → 0; pytest stayed
**128 passed** after every batch).

| Batch | Region | Errors | Fix (no ignore / no Any / no config change) |
|---|---|---|---|
| profiles.py classes | B024 | 1 lint | `Profile(ABC)` gained `@abstractmethod area()`; `CircleProfile.area = π r²`, `RectProfile.area = w·h` (prompt-blessed minimal abstract member; nothing instantiates `Profile` directly, runtime-neutral) |
| profiles.py `_center2` | 62, 66 | 2 | two-step guard + `cast("Sequence[object]", value)` — the `_b123_ops._parse_center` shape |
| profiles.py `profile_from_mapping` | 80–103 | 13 | `params = cast("Mapping[str, object]", value)` after the isinstance guard; every `.get/set/[]` goes through the typed local (grammar.py `_as_mapping` pattern) |
| `_profile_section` | 79–83 | 8 | `cx, cy = profile.center` moved inside both isinstance branches (sealed set); no base-class field reorder — constructor signatures untouched |
| `_revolve_axis` | 164, 166 | 2 | `cast("Sequence[object]", value)`; len-gate split keeps the single final error message |
| `_revolve` call | 203 | 1 | `cast("Face | Iterable[Face]", section)` — Sketch iterates its faces at runtime; the stub's `__iter__: Iterator[Shape]` is coarser |
| `_fillet` | 225–246 | 4 | two-step guard + one `cast("Sequence[EdgeSelector | Mapping[str, object]]", edges_raw)` typing the whole loop (no per-item narrowing, no new runtime checks); `_normalize_result(cast("Part | Compound | Wire", result))` bridges fillet's `Solid \| Part` stub |
| `_tool_solid` | 260–273 | 10 | `params = cast("Mapping[str, object]", tool)` after the guard |
| `_descriptor_json` | 315 | 1 | `dict(cast("Mapping[str, object]", selector))` |
| `_parse_hole_fields` | 339–364 | 13 | `selector_typed` / `position_map` / `depth_map` typed locals via cast after each isinstance guard |
| `_parse_polar_pattern` + `_hole_pattern` base | 467–510 | 9 | `params` / `base_map` cast locals |

### Remaining 6 — BLOCKED (out of whitelist)

`_b123_features.py:46-51` `reportPrivateUsage`: the import block pulling
`_checked_mapping / _normalize_result / _parse_center / _parse_mode /
_parse_positive / _reject_unknown_keys` from `mycad.geom._b123_ops` (T2's
private helpers). NOT the Mapping-poison class the dispatch described —
it is pyright's module-private rule, and it has **no fix inside the
whitelisted files**:

- probe-verified: `from x import _p`, `from x import _p as q`, and
  `import x` + `x._p` are ALL flagged; only importing the private *module*
  itself is clean;
- `# pyright: ignore` banned (T3 bar "no ignore"; `test_layering.py`
  enforces zero suppression sites by intent);
- `getattr`/`__dict__` routing returns Any (banned);
- duplicating the ~60 lines of helpers into `_b123_features.py` violates
  the "只做类型收窄/lint/format" no-design-change mandate (drift hazard).

**Root cause**: cross-module private imports. The commands layer keeps
all cross-module imports public (`schema_matches`); `_b123_features`
reaching into `_b123_ops`'s privates is the anomaly. **Recommended fix**
(requires adding `src/mycad/geom/_b123_ops.py` to the whitelist — the
module is itself package-private, so no public API changes): rename the
six symbols public (~27 internal call sites) OR append public aliases
(`checked_mapping = _checked_mapping`, …) and import the public names in
`_b123_features.py`. Zero runtime change either way; pyright then reads 0.

### Incidental finding (pre-existing, out of whitelist)

`tests/test_layering.py::test_no_type_ignore_or_pyright_ignore_sites` is
a latent no-op: it skips files with `path.suffix not in ("py",)` but
`Path.suffix` is `".py"` (with the dot), so no file is ever scanned —
which is why two `# type: ignore[misc]` sites in `tests/core/` pass
unnoticed. Not fixed here (test logic frozen for this task); flagged for
the orchestrator.

### Gates (final, scoped, 2026-10-05T01:53Z)

- `uv run pytest tests/geom/ tests/test_layering.py -q` → **128 passed**
- `uv run ruff check src/mycad/geom tests/geom` → **0 errors**
- `uv run ruff format --check src/mycad/geom tests/geom` → **clean**
- `uv run basedpyright src/mycad/geom tests/geom` → **6 errors** (the
  BLOCKED import block above; down from 69)
- 后续修复：6 个 reportPrivateUsage 已由 rename 私有→公共（_b123_ops.py 内共享 helper 转正式包内 API）消除，scoped pyright 归零。
