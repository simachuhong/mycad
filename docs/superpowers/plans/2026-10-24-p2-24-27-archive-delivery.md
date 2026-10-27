# P2-24–27 Archive, Platform, Delivery, and Governance Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task. Each implementation step starts with a focused regression or characterization check; no commit is included because the current feature workspace contains earlier uncommitted Phase 2 work.

**Goal:** Define a durable, honest archive and support contract for Phase 2, reduce the default headless install to the geometry/runtime requirements, and collect the delivery evidence that can be verified without publishing the current uncommitted branch.

**Architecture:** Keep `.mc.json` v1 immutable and document the exact scope of replay, object identity, and crash recovery. Move Qt/GL packages to a `desktop` extra while retaining geometry packages as core dependencies; make the CLI explain how to install the extra. Validate clean headless and desktop environments, then keep any acceptance requiring a pushed revision, Windows runner, or unavailable desktop modality explicitly partial.

**Tech Stack:** Python 3.12–3.14, uv, hatchling, existing `.mc.json` v1 validator/migration hook, PySide6/pyqtgraph optional extra, GitHub Actions, existing pytest/Ruff/basedpyright gates.

**Spec:** `.omo/plans/phase2-agent-loop.md` P2-24 through P2-27; ADR-002, ADR-006; `docs/design/profile-workplane-dimensions.md`; P2-11/17 decisions.

## Global Constraints

- Preserve `.mc.json` v1 top-level keys and command audit fields `id/version/params/ordinal/timestamp_utc/confirmed_by` exactly.
- Do not add sketch, stable object identity, BREP checkpoint, plugin provenance, or enterprise fields to v1.
- Keep the exact dependency pins for build123d and cadquery-ocp-novtk; do not add dependencies.
- T1 CI remains Ubuntu 22.04/24.04 and Windows; do not add QEMU/LoongArch CI.
- State the difference between installed-wheel evidence, QEMU execution, native hardware, and unverified platform claims.
- No push, release, PR, or commit that could absorb prior uncommitted changes.

## Review Focus

- A current v1 archive remains readable even if the writer changes later.
- A failed file replacement keeps the old archive and never marks the document clean.
- Default/headless installation does not require Qt/GL wheels; desktop installation includes all required optional packages.
- Missing desktop dependencies produce an actionable `mycad gui` message without breaking CLI imports.
- README/ADR/NOTICE claims distinguish headless glibc requirements, desktop requirements, QEMU evidence, no-go platforms, and actual support.

## Tasks

### Task 1: P2-24 archive and recovery contract

**Files:**
- Create: `tests/fixtures/archives/v1_cylinders.mc.json`
- Create: `docs/adr/ADR-008-persistence-reproducibility-and-recovery.md`
- Modify: `tests/core/test_persistence.py`
- Modify: `.omo/plans/phase2-agent-loop.md`
- Create: `.omo/evidence/task-P2-24-phase2-agent-loop.md`

**Interfaces:** v1 archive remains the only implemented archive format. Runtime IDs stay ephemeral. `migrate()` stays a pure dictionary transform and the shipped registry remains empty until an actual next-version schema is approved.

- [ ] Add `test_static_v1_archive_fixture_opens_and_preserves_audit_fields`; demonstrate the absent fixture fails first.
- [ ] Add a failed-`os.replace` regression proving old bytes, dirty state, and temp-file cleanup; record whether current behavior already satisfies it.
- [ ] Record in ADR-008: what v1 can reproduce, command/plugin/kernel/tolerance provenance gaps, current-history versus append-only audit semantics, Save As/reopen identity semantics, migration requirements, and why durable backups/power-loss recovery are deferred.
- [ ] State the v2 trigger and required data owners for sketch/profile identity and provenance; do not implement a speculative v2 schema before P2-32/35.
- [ ] Run persistence and exception-taxonomy tests; add P2-24 evidence; mark P2-24 complete only when each acceptance is addressed.

### Task 2: P2-25 headless and desktop package split

**Files:**
- Modify: `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`, `NOTICE`, `README.md`, `docs/adr/ADR-006-platform-tiering.md`
- Modify: `src/mycad/cli/__main__.py`, `tests/test_scope_audit.py`, `tests/test_notice.py`
- Create: `tests/cli/test_optional_desktop.py`, `scripts/verify_headless_install.py`, `.omo/evidence/task-P2-25-phase2-agent-loop.md`

**Interfaces:** `[project.optional-dependencies].desktop` owns `PySide6`, `pyqtgraph`, and `PyOpenGL`; `dependencies` continues to own the geometry/runtime stack. CI's UI/full suite installs `--extra desktop`.

- [ ] Add a test that blocks a Qt import and asserts `mycad gui` exits with an install hint; verify it fails before the change.
- [ ] Move only the three desktop dependencies into the `desktop` extra; preserve every geometry pin and regenerate `uv.lock`.
- [ ] Make NOTICE attribute both the default runtime closure and the optional desktop closure; update audits so core has no Qt dependency and both closures are complete.
- [ ] Add a clean headless CLI smoke that writes STEP/STL/`.mc.json` under a temporary directory; run it in a no-dev environment without the desktop extra.
- [ ] Change the quality CI sync to `--extra desktop`; add a separate Ubuntu 22.04 headless install/smoke job.
- [ ] Align README and ADR-006: T1 desktop, T2 headless versus desktop glibc floors, T3 no-go, Windows, and unsupported/untested platforms.
- [ ] Verify headless and desktop installs in fresh environments, lock consistency, NOTICE and scoped checks; record P2-25 evidence.

### Task 3: P2-26 delivery evidence

**Files:**
- Create: `.omo/evidence/task-P2-26-phase2-agent-loop.md`
- Read/verify: `.github/workflows/ci.yml`, installation instructions, real desktop, STEP sample.

- [ ] Record exact HEAD, worktree status, OS/architecture/Python/glibc, display backend, and which installation/run paths were executed.
- [ ] Run all locally available gates and a real desktop launch/render/save smoke if the current display is usable; separate this from offscreen tests.
- [ ] Inspect current-HEAD remote CI availability and available downstream CAD tooling without pushing or publishing uncommitted work.
- [ ] Mark P2-26 partial unless the exact submitted revision has T1 CI, the supported real desktop modalities, clean install, and downstream STEP inspection evidence. List every uncovered item.

### Task 4: P2-27 documentation and governance sync

**Files:**
- Modify: `README.md`, `AGENTS.md`, `.omo/plans/phase2-agent-loop.md`, relevant ADRs and test documentation.
- Modify: `tests/fixtures/baseline_doc_sha256.json` only if a protected tracked document changes.
- Create: `.omo/evidence/task-P2-27-phase2-agent-loop.md`

- [ ] Reconcile status and terminology against current task evidence; retain P2-12 and P2-19 as partial and distinguish E04's old observation from the corrected current-pick contract.
- [ ] Remove stale platform/stage/API/count claims that the E tasks supersede; do not rewrite historical records or claim the full Phase 2 release gate.
- [ ] Verify links, task dependencies/statuses, audit-field and layering invariants, README install commands, and documentation hash guards.
- [ ] Record P2-27 evidence and mark complete only after scoped document and contract checks pass.

## Plan Decisions

- P2-24 is a decision plus compatibility/recovery regression task; it does not force a format-v2 implementation without a consumer schema.
- P2-25 adopts an optional desktop extra because the CLI already imports the UI lazily and the geometry wheel floor is lower than the current aarch64 Qt wheel floor.
- P2-26 cannot be completed by pushing or creating a PR without separate authorization; current branch changes remain uncommitted and must not be bundled.
