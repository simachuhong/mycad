# Phase 0 / T3 evidence — command framework (Wave 1)

**Task**: T3 — CommandSpec / JSON-Schema-subset validation / registry /
bidirectional CLI grammar (spec.py, validation.py, registry.py, grammar.py,
demo.py + tests/commands/).
**Plan**: `.omo/plans/phase0-mvp.md` lines 223–253 (todo), 26–58 (guardrails),
75–91 (verification), 550+ (Appendix A — cylinder schema authority).
**UTC timestamp**: 2026-10-04T14:29:18Z (closer pass; original delivery by a
prior agent that died before writing this evidence file, finished per the
re-diagnosis below).
**Environment**: Linux x86_64, Python 3.12.3, uv; stdlib only (no
pydantic/jsonschema — plan Must-NOT).

## 0. Closer re-diagnosis (this session)

The prior agent delivered the full T3 code and tests (all scoped tests green
on arrival) but died before writing evidence. Fresh diagnosis:

- basedpyright strict: **28 errors remained** in `src/mycad/commands/` +
  `tests/commands/` — all typing-level (Unknown leakage from `isinstance`
  narrowing on `object`-typed schema dicts, one `Mapping`-vs-`dict` return
  annotation, one unused variable, two readonly-attribute assignments in the
  frozen-dataclass tests). Finished to 0 with no behavior change (§5).
- No runtime defects found: `uv run pytest tests/commands -q` was 122 passed
  on arrival and stayed 122 passed after every typing fix.
- This evidence file written from the delivered code + fresh scoped runs
  (§2, §6) + a fresh tamper probe (§4).

## 1. Component inventory (delivered code)

| File (lines) | Contents |
|---|---|
| `src/mycad/commands/spec.py` (61) | `CommandSpec` frozen dataclass, field order fixed: `id, version, summary_en, label_zh, params_schema, cli, undo_compensation="history_replay"` (last field carries default; `__post_init__` rejects any other value with ValidationError); `CliSyntax(verb_aliases: tuple[str,...], positional=())`; `UndoCompensation = Literal["history_replay"]` |
| `src/mycad/commands/validation.py` (436) | `validate_params(spec, params, defs=None)` — self-implemented fixed JSON-Schema subset, keyword allowlist enforced (out-of-list keyword → error, not ignore): type (integer rejects bool) / properties+required / additionalProperties:false / items / minItems·maxItems / minimum·maximum·exclusiveMin·Max / minLength·maxLength / enum / const / default (fill-missing, explicit null rejected) / oneOf (exactly-1, per-branch first errors) / `$defs`+`$ref` (`#/$defs/<Name>` only, root-level `$ref` supported, bad prefix/out-of-table names fail) / description (doc only); `schema_matches` predicate shared with grammar; `normalize_params` — #round9-3 delete-key semantics (FaceSelector `axis=""` deleted iff `surface=="cylinder"`, plane+`""` defensively raises; EdgeSelector `curve=""` deleted; nothing else transformed, never produces None), idempotent |
| `src/mycad/commands/registry.py` (130) | `CommandRegistry(schema_defs=None)` — the single defs injection point (`registry.schema_defs`); register/get/list_by_category/search; category derived from id first segment (`feature.cylinder`→"feature"); same-version re-register → `CommandConflictError`, different versions coexist latest-wins (API-tested, unused in phase 0); search matches id + verb_aliases + summary_en, case-insensitive substring, NOT label_zh, returns id-sorted list |
| `src/mycad/commands/grammar.py` (534) | `parse_line(text, registry)` / `to_cli(id, params, registry)` mutually inverse; registry injected (verb resolution walks `cli.verb_aliases`, no module-level verb table); 4 value lexemes exactly (int/float, true/false, double-quoted with `\"`/`\\` escapes, bare identifier with leading sign); flat dotted keys `key.sub=v`, digit-index keys `key.0.sub=v`, `[...]` only for scalar arrays; `to_cli` emits ALL keys incl. default-filled in schema `properties` declaration order (root `$ref` → referenced def order), integer-valued floats without decimal point; 3 mutually exclusive error layers (CliSyntaxError / UnknownCommandError(identifier=verb) with SequenceMatcher suggestion / ValidationError); 6 mandated examples in docstring each with round-trip test |
| `src/mycad/commands/demo.py` (61) | `DEMO_SCHEMA_DEFS` (Mode/Center3/Positive prototype — deliberately NOT `COMMAND_SCHEMA_DEFS`, no second formal table), `cylinder_spec()` (Appendix A.1 verbatim: radius/height Positive, center Center3 default [0,0,0], mode default new, `summary_en="Create a cylinder"`, `label_zh="圆柱体"`), `demo_registry()` |
| `src/mycad/commands/__init__.py` (16) | exports `CliSyntax`, `CommandSpec` |
| `tests/commands/_fixtures.py` (435) | inline minimal defs fixtures + synthetic specs/registries (per #round9-7 — imports nothing from the not-yet-existing `builtin_commands.defs`) |
| `tests/commands/test_validation.py` (41 tests) | schema subset matrix: type/bounds/enum/const/defaults/items/array bounds/oneOf (0, 1, ≥2 branches)/$ref (good, bad prefix, out-of-table)/unknown keyword rejection/dotted-path messages/FaceSelector oneOf branch discipline ①–⑤ |
| `tests/commands/test_grammar.py` (34) | 6 docstring examples round-trip; 20+ case parse→to_cli→parse property; bare-identifier lexeme rules (signed `+Z` keeps sign, `s=true` string per schema, `mode=banana` semantic-not-lexical, quoted-with-space); key order; integer-valued float canonicalization; defaults always explicit; 3 error layers ≥2 cases each, types never mixed |
| `tests/commands/test_normalize.py` (15) | axis/curve delete-key at all 3 nesting positions (hole.target_face, hole_pattern.base_hole.target_face, fillet.edges[].parent_faces[]); plane+`""` defensive raise; validate→normalize→validate idempotent closed loop; explicit null rejected at validation; untouched keys deep-equal; purity |
| `tests/commands/test_registry.py` (20) | category grouping (feature 6 / modify 2 in synthetic registry), id-sorted, same-version conflict, version coexistence, search semantics a/b/c (id substring, alias/summary hit, no-hit → `[]`), defs injection |
| `tests/commands/test_spec.py` (7) | field order contract, frozen (FrozenInstanceError), undo_compensation default + rejection, label_zh as data, CliSyntax defaults, Appendix-A verbatim spec comparison |
| `tests/commands/test_demo.py` (5) | demo registry wiring, defs shape, spec equality, `$ref` resolution through registry defs |

Commands layer imports stdlib only — no build123d/OCP/numpy (guarded by
`tests/test_layering.py`, which whitelists those imports only in
`src/mycad/geom/`, `tests/geom/`, `tests/helpers/step_roundtrip.py`).

## 2. QA happy path (manual channel, per plan QA scenario)

`uv run python -c` one-shot script: register cylinder → parse → validate →
assert dict → normalize → to_cli → re-parse round-trip (all assertions inline):

```
OK  parse: feature.cylinder {'radius': 40, 'height': 8}
OK  validate+normalize: {'radius': 40, 'height': 8, 'center': [0.0, 0.0, 0.0], 'mode': 'new'}
OK  to_cli: cylinder radius=40 height=8 center=[0,0,0] mode=new
OK  roundtrip parse_line(to_cli(...)) == (id, params)
```

Defaults are filled by validation (center [0.0,0.0,0.0], mode "new"),
`to_cli` emits them explicitly with integer-valued floats canonicalized
(`[0,0,0]`), and the canonical line re-parses to the same validated+normalized
params — the §"往返门" closure for the demo command.

## 3. Failure classes — 4 types, mutually exclusive (per plan QA)

All four mandated failure scenarios have dedicated tests asserting the exact
exception type (a type never doubles for another layer):

| Input | Exception | Test |
|---|---|---|
| `cylinder radius=-1 height=8` | `ValidationError` (exclusiveMinimum 0; radius lexically a legal integer) | `test_layer3_negative_radius_is_validation_error` |
| `cylnder radius=4 height=8` | `UnknownCommandError`, `identifier == "cylnder"`, message suggests `cylinder` | `test_layer2_unknown_verb_with_suggestion` |
| `cylinder radius=abc height=8` | `CliSyntaxError` pointing at token | `test_layer1_number_literal_required_for_number_key` |
| `cylinder radius=1 height=2 extra=1` | `ValidationError` (unknown key, semantic layer — parse_line itself succeeds) | `test_layer3_unknown_key_is_validation_error_not_clisyntax` |

Plus: lexical layer fires before verb resolution even on unknown verbs
(`'cylnder radius="4 height=8'` → CliSyntaxError, never UnknownCommandError)
and the bare `=`/unclosed-bracket/untokenizable cases
(`test_layer1_bare_equals_is_clisyntax_error`,
`test_layer1_unclosed_scalar_array_bracket`, …).

## 4. normalize_params tamper proof (red → restore → green)

Target: the #round9-3 delete-key semantic — `src/mycad/commands/validation.py`
line `del normalized["axis"]` inside `_normalize_value`. Tamper: replaced the
deletion with `normalized.setdefault("axis", "")` (key survives with `""`),
backup kept in /tmp (never inside the repo):

```
uv run pytest tests/commands/test_normalize.py -q   (tampered)
  -> FAILED test_axis_empty_deleted_at_hole_target_face
  -> FAILED test_axis_empty_deleted_at_hole_pattern_base_hole
  -> FAILED test_axis_empty_deleted_inside_fillet_parent_faces
  -> FAILED test_untouched_keys_deep_equal_and_no_none_axis_curve
  -> 4 failed, 11 passed in 0.15s
```

Restored from backup (byte-identical, `cmp` verified, backup then deleted),
re-ran:

```
uv run pytest tests/commands/test_normalize.py -q   (restored)
  -> 15 passed in 0.05s
```

Red→green closed: the delete-key tests are load-bearing, not vacuous.

## 5. Closer cleanup — basedpyright strict 28 → 0

| Path | Errors | Fix (no ignore / no Any / no config change) |
|---|---|---|
| `src/mycad/commands/grammar.py` | 17 | `isinstance(x, dict)` on `object` narrows to `dict[Unknown, Unknown]`, poisoning returns and loop vars → new `_as_dict` helper (same shape as existing `_as_mapping`) returning `dict[str, object] \| None`; `_materialize` iterates/returns the typed local; `_deref_required` return annotation corrected `dict[str, object]` → `Mapping[str, object]` (callers only use Mapping ops; runtime unchanged); oneOf `branches` cast to `list[object]` before iteration (`branch: object \| None`); `_emit_value` casts isinstance-narrowed `Mapping`/`list` to `Mapping[str, object]`/`list[object]` |
| `src/mycad/commands/validation.py` | 2 | `_branch_matches` receives the already-cast `branch_list` instead of the isinstance-narrowed `branches`; `deepcopy(resolved["default"])` reads through `default_schema = cast("dict[str, object]", resolved)` |
| `tests/commands/test_grammar.py` | 1 | unused `command_id` → `_` in the quoted-value test |
| `tests/commands/test_normalize.py` | 6 | `_collect_axis_curve_values` iterates `cast("dict[str, object]", node).items()` / `cast("list[object]", node)` |
| `tests/commands/test_spec.py` | 2 | frozen-dataclass readonly assignment `spec.version = 2` (flagged by `reportAttributeAccessIssue`) → `spec.__setattr__("version", 2)`: invokes the same generated frozen `__setattr__` so `FrozenInstanceError` is still raised (test still passes, behavior identical); the `setattr()` builtin alternative is rejected by ruff B010, the method call satisfies both gates without suppression |

Scoped tests stayed green after every single-file fix (240 passed before and
after; the frozen tests still genuinely exercise `FrozenInstanceError`).

## 6. Scoped verification (all exit 0, 2026-10-04T14:29:18Z)

```
uv run pytest tests/geom tests/commands tests/test_layering.py -q
  -> 240 passed in 12.52s   (122 of them in tests/commands)
uv run ruff check src/mycad/geom src/mycad/commands tests/geom tests/commands tests/test_layering.py
  -> All checks passed!
uv run ruff format --check src/mycad/geom src/mycad/commands tests/geom tests/commands tests/test_layering.py
  -> 27 files already formatted
uv run basedpyright src/mycad/geom src/mycad/commands tests/geom tests/commands tests/test_layering.py
  -> 0 errors, 0 warnings, 0 notes
```

`tests/snapshots/` does not exist (plan Must-NOT; verified).

## 7. Adversarial classes

- **malformed_input** — probed by the suite: unknown keys, type errors,
  bounds violations, enum/const mismatches, oneOf 0/≥2 branches, bad `$ref`
  prefix and out-of-table names, out-of-allowlist schema keywords, unclosed
  quotes/brackets, bare `=`, non-contiguous array indices — each raises the
  layer-correct exception with dotted paths / offending tokens in messages.
- **flaky_tests** — n/a: no floats-compared-to-goldens in commands tests;
  grammar round-trips are exact string/dict equality.
- **misleading_success_output** — probed: §2 happy path asserts dicts against
  literal expected values inside the script; §4 tamper probe proves the
  normalize tests fail when the semantic is removed.
- **stale_state** — n/a: `normalize_params` is pure (purity-tested:
  `test_normalize_is_pure_against_input`), registry operations are additive;
  demo helpers construct fresh instances per call.
- **prompt_injection / cancel_resume / hung_commands / repeated_interruptions**
  — n/a this session (closer pass, single-threaded, path-scoped commands only).
- **dirty_worktree** — integration-owned; no git operations performed
  (`src/mycad/commands/`, `tests/commands/` are untracked Wave-1 deliverables).

## 8. Deviations

1. Evidence file written by the closer agent (this session), not the original
   author — the prior agent died before writing it; content derived from the
   delivered code and fresh runs, per the re-diagnosis in §0.
2. `DEMO_SCHEMA_DEFS` in `demo.py` is named differently from the formal
   `COMMAND_SCHEMA_DEFS` on purpose (plan #round9-7 forbids a second formal
   table in Wave 1); this is plan-compliant naming, not a deviation.
3. The frozen-dataclass tests use `obj.__setattr__("attr", value)` instead of
   direct attribute assignment (basedpyright readonly check vs ruff B010
   conflict); the generated frozen `__setattr__` is still the code path
   exercised, so the tested behavior is unchanged.

No other deviations. Sibling scopes (`src/mycad/geom/**`, `tests/geom/**`,
`tests/test_layering.py`) untouched by T3 work; typing fixes in this session
touched only the files listed in §5.
