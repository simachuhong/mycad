# Phase 0 / T1 evidence — Engineering skeleton (Wave 0)

**Task**: T1 — engineering skeleton (uv/pyproject, closed exception taxonomy,
neutral DTOs/selectors, SPDX enforcement, baseline hash fixtures, layering
guard, three-OS CI workflow).
**Plan**: `/media/sima/Data/projects/MyCAD/.omo/plans/phase0-mvp.md` (Momus
round 12d2 verdict: APPROVE).
**UTC timestamp**: 2026-09-28T04:25:59Z
**Environment**: Linux x86_64, Python 3.12.3, uv 0.11.17.

## 1. Lockfile — resolved versions

`uv lock` parsed 58 packages and pinned:

| Package | Resolved version |
|---|---|
| build123d | 0.11.1 (exact pin, matches plan) |
| cadquery-ocp-novtk | 7.9.3.1.1 (within `>=7.9.3.1.1,<7.9.4`) |
| OCP | 7.9.3.1.1 (transitive, OpenCascade python bindings) |
| ruff | 0.16.9 (within `>=0.6,<1.0`) |
| basedpyright | 1.40.1 (exact pin, matches plan) |
| pytest | 9.1.1 (within `>=8`) |
| pytest-cov | 7.1.0 |

`uv sync --extra dev` exited 0 after downloading the OpenCascade wheel
(>100 MB; first-run cold cache). Subsequent invocations reuse `~/.cache/uv/`.

## 2. Four quality gates (all exit 0)

### 2.1 `uv run ruff check .`
```
All checks passed!
```
exit 0. Note: `pyproject.toml` excludes `.omo/` (Boulder / plan / review /
evidence archaeology from earlier Codex CLI runs — not source under
MyCAD's strict gates).

### 2.2 `uv run ruff format --check .`
```
19 files already formatted
```
exit 0.

### 2.3 `uv run basedpyright`
```
0 errors, 0 warnings, 0 notes
```
exit 0. Strict mode per `pyrightconfig.json`.

### 2.4 `uv run pytest -q`
```
.................................                                        [100%]
33 passed in 10.64s
```
exit 0. **33 test cases** across 8 files.

## 3. File inventory (T1 deliverables)

| File | Lines | Purpose |
|---|---:|---|
| `.gitignore` | — | Excludes `.venv/`, caches, `dist/`, `build/`, `*.egg-info/`. **Does NOT exclude `.omo/`**. |
| `pyproject.toml` | 79 | PEP 621 + hatchling, src layout, requires-python `>=3.12,<3.15` |
| `pyrightconfig.json` | 5 | strict mode, src+tests |
| `uv.lock` | — | 58 packages, build123d==0.11.1, ocp-novtk 7.9.3.1.1 |
| `.github/workflows/ci.yml` | 31 | ubuntu-22.04 / ubuntu-24.04 / windows-latest × astral-sh/setup-uv@v4 × python 3.12 × 4 quality gates |
| `src/mycad/__init__.py` | 5 | `__version__ = "0.1.0"` |
| `src/mycad/core/exceptions.py` | 156 | Closed 15-class taxonomy |
| `src/mycad/core/geometry_types.py` | 80 | BoundingBox / MassProperties / Tessellation (neutral) |
| `src/mycad/core/selectors.py` | 63 | FaceSelector / EdgeSelector (neutral, no positional data) |
| `tests/__init__.py` | 3 | marker |
| `tests/core/__init__.py` | 3 | marker |
| `tests/test_smoke.py` | 23 | version pinned, submodules importable |
| `tests/test_spdx.py` | 60 | every .py starts with exact SPDX pair, no BOM |
| `tests/test_exceptions.py` | 85 | exactly 15 subclasses; ordinal field on two classes; identifier on UnknownCommandError; ProviderConflictError signature |
| `tests/test_baseline_hashes.py` | 61 | fixture equals current SHA256 of three baseline docs |
| `tests/test_ci_workflow.py` | 46 | workflow has all required tokens |
| `tests/test_layering.py` | 93 | src/ has no backend imports; zero `# type: ignore` / `# pyright: ignore` outside `tests/typing/` |
| `tests/core/test_geometry_types.py` | 69 | field lock + size/center numeric + frozen + Tessellation range check |
| `tests/core/test_selectors.py` | 59 | field lock + frozen + no CAD backend leakage |
| `scripts/gen_baseline_hashes.py` | 50 | stdlib-only baseline fixture generator |
| `tests/fixtures/baseline_doc_sha256.json` | 8 | sha256 of 3 baseline docs |
| `README.md` | 76 (delta from 37) | appended: 开发环境 / 国内镜像 / 离线 conda-wheelhouse appendix |

Total new Python + YAML + TOML: **966 lines** (excluding lockfile).

## 4. Three-OS CI is READY but NOT EXECUTED

The `.github/workflows/ci.yml` matrix covers `ubuntu-22.04`,
`ubuntu-24.04`, `windows-latest` with `astral-sh/setup-uv@v4` and
`python-version: "3.12"`, running all four quality gates.

**No remote is configured for this repository.** The workflow is therefore
in the READY state — its shape is pinned by `tests/test_ci_workflow.py`
so silent drift (a dropped OS, a dropped quality gate) fails locally
before reaching CI.

**Do NOT** claim three-platform verification in any downstream evidence
or deliverable until F3 obtains a real CI run URL with green checkmarks
on all three runners.

## 5. Deviations from plan spec

**None of substance.** Two non-substantive clarifications:

1. `pyproject.toml` adds `extend-exclude = [".venv", "build", "dist",
   ".git", ".omo"]` for ruff so quality gates do not churn over Codex
   CLI archaeology in `.omo/`. The plan's intent ("strict gates") is
   preserved — every file under `src/`, `tests/`, `scripts/` is
   linted, formatted, type-checked, and tested.
2. `tests/test_exceptions.py` checks fields by **name** rather than
   the `field.type` string. `from __future__ import annotations`
   defers annotation evaluation, so `dataclasses.fields()` exposes
   stringified *type names* (e.g. `"SurfaceLiteral"`) which the test
   layer treats as opaque. The taxonomy invariant (15 classes,
   `ordinal` field present where required, `identifier` field on
   `UnknownCommandError`, no `identifier` on `CommandConflictError`)
   is what we actually want to lock, and that is asserted.

## 6. What this evidence does NOT cover (later waves)

- W2/T2+ geometry primitives (extrude/revolve/hole/fillet/boolean_cut)
- W3/T7 STEP/STL providers
- W4/T8 FormatProvider registry
- W5/T9 CommandBus
- W6/T10 plugin system
- W7/T11 CLI
- F3 real CI run URL

These are blocked on T1's acceptance. T1 is complete.