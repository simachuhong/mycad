# Todo 14: README + AGENTS.md + docs sync — evidence

Commit: `docs: gui quickstart, layering rules, and implementation notes`

## Changes (6 files)

- `README.md`: tech-stack UI line + status section re-titled to phase 1 + phase-1
  delivery bullet + "尚未开始" line now says shell delivered (agent loop remains) +
  quick start gains `uv run mycad gui` with `QT_QPA_PLATFORM=offscreen` tip +
  stale "文档与规格阶段" contribution wording dropped. No marketing copy added.
- `pyproject.toml`: description Phase 0 MVP -> Phase 1 desktop shell.
- `AGENTS.md`: OVERVIEW phase wording (phase 1 shipped, 882 tests), agent bullet
  gains GUI plan-card confirmation clause, README-sync bullet gains `mycad gui`,
  STRUCTURE tree gains `src/mycad/ui/` row (only-PySide6 clause), CODE MAP gains
  `MainWindow` + `GLViewport` rows, CONVENTIONS T1 rules gain the ui clauses
  (ui imports PySide6/shiboken6 exclusively; bans build123d/OCP/mycad.geom;
  allows numpy; tests/ui added to the backend-import whitelist).
- `docs/技术路线.md` §9: one-line PySide6 LGPLv3 dynamic-link assessment note.
- `docs/UI设计初稿.md`: appended "实现注记（阶段 1 落地差异）" — Chat page is a
  plan-card stream (NL conversation = phase 2), toolbar actions deferred (dock +
  QSettings memory shipped), CLI tab mirrors headless execute_line verbatim
  (quit does not close the GUI), picking uses math ray×triangle (not
  glReadPixels color readback).
- `tests/fixtures/baseline_doc_sha256.json`: hashes updated for the 2 edited docs.

## Scope-audit baseline mechanism (key finding)

`test_tree_boundaries_docs_baseline_unchanged` iterates over the baseline JSON's
own keys — the original baseline deliberately tracked exactly 3 docs
(需求分析书 / 技术路线 / UI设计初稿). ADRs are intentionally out of scope. A first
rewrite expanded the baseline to all 9 tracked docs and was REVERTED to the
original 3-key scope (only recomputing the 2 edited docs' hashes), because todo
16 must still edit ADR-006 and expanding the checked set would turn a planned
edit into a baseline chore. Red->green: baseline test failed before the hash
update (assert pair printed), passed after.

## Gates

- `QT_QPA_PLATFORM=offscreen timeout 25 uv run mycad gui`: rc=124 (started,
  event loop ran until timeout kill); only harmless
  "plugin does not support propagateSizeHints()" offscreen warnings.
- `uv run ruff check .` clean; `uv run ruff format --check .` 187 files;
  tree-wide `basedpyright` 0 errors / 0 warnings / 0 notes.
- `uv run pytest tests/test_scope_audit.py -q` = 21 passed (baseline synced).

## Must-NOT compliance

- No marketing copy; ADR-001..005 untouched; ADR-006 untouched (todo 16);
  需求分析书 body untouched (only 初稿/技术路线 annotated).
