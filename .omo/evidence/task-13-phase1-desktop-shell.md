# Todo 13 evidence — unskip UI layout acceptance + full regression gate

## Change
- tests/test_acceptance_flange.py: `test_ui_layout_acceptance` unskipped; lands the
  UI初稿 §11 five items (five-zone skeleton + menu/toolbar/status bar; toolbar hide +
  edge move; right pane 结构/属性/选项(+显示/测量占位) tabs; palette discoverability
  apply_filter("")==8 / "box"==1; Chat plan cards confirm-gated modeling) plus the
  §8.3 minimal workflow: controller drafting -> plan.confirm(actor="gui") via
  PlanCards.execute_plan -> STEP export -> bus.undo(len(plan.steps)) restores the
  pre-plan document state (0 commands).
- tests/ui/conftest.py: autouse `discard_unsaved_dialog` patches
  MainWindow._ask_save_dialog -> "discard" for every tests/ui test (per-file patches
  were the previous state; per-file patches registered later still win).

## Root cause (found with faulthandler_timeout)
Full-suite runs stalled at 81% (solo runs of every lane were green). The dump showed
pytest-qt `_close_widgets` -> MainWindow.closeEvent -> _confirm_unsaved_changes ->
QMessageBox.exec() blocking forever offscreen on a dirty document at teardown. Fixed
by the conftest autouse discard patch + an in-test patch inside the acceptance test
(root lane; its own document goes dirty after confirm).

## Full four gates (Linux, local)
- `uv run pytest -q`             -> 882 passed in 113.22s (phase-0 baseline 802 + UI additions)
- `uv run ruff check .`          -> all clean
- `uv run ruff format --check .` -> 187 files already formatted
- `uv run basedpyright`          -> 0 errors, 0 warnings, 0 notes (strict, zero suppression)

## Red-green probe
- probe: changed the post-undo assertion to `== 1  # probe` -> test FAILED
- revert -> test PASSED again (red-green closed)

## Acceptance criteria
- [x] pytest full run green (882)
- [x] ruff check / format / basedpyright tree-wide green
- - [ ] CI three-platform green (BLOCKED ON PR: ci.yml triggers only on push→main or any pull_request; feature-branch push 2084fc2 did NOT start a run — confirmed via Actions API total_runs=7, all Oct 11 on main. Origin has 2084fc2 (ls-remote verified). Manual draft PR from phase1-desktop-shell → main is the gate trigger; no GitHub API token in env (SSH-only remote) so the PR must be opened by the user at https://github.com/simachuhong/mycad/compare/main...phase1-desktop-shell or via a provided token. (pushed with this commit; tracked in ledger)
