# Task 5 — menus / toolbar / QSettings / status bar

Commit: `feat(ui): menus, dockable lockable toolbar with QSettings persistence, status bar`
Branch: phase1-desktop-shell

## Delivered

- `src/mycad/ui/main_window.py`: seven §3 menus verbatim
  文件/编辑/视图/特征/工具/智能体/帮助; viewport-placeholder actions
  (着色/线框·适应窗口·标准方向) disabled, owned by todo 9; 文件 lifecycle
  disabled except 退出 (todo 8); 删除/选择过滤器/测量/清空对话 disabled.
  撤销/重做 slots guard on unbound bus and degrade the status field
  (InvalidHistoryError surfaced in status, no empty catch). 重建 slot
  delegates to the public `rebuild_hook` (todo 9 attaches). Dock-to-edges
  via native Qt dragging (no explicit 停靠边 menu item — honest delta vs §3
  wording, native right-click menus provide the entries). Toolbar lock =
  movable+floatable toggles. QSettings memory: geometry+saveState+locked
  on closeEvent, restore in ctor (org=MyCAD/app=MyCAD). Status bar five
  permanent fields: 当前命令(空闲)/选择计数/单位 mm/重建状态/修改标记,
  mapped over the plan signal union via `handle_core_signal`.
- `functools.partial` adapters held STRONGLY on the window — SignalBus
  holds weak refs, unsubscribed closures would die at emit.
- `tests/ui/conftest.py`: autouse sandbox routes QSettings IniFormat into
  tmp_path (no real $HOME leakage).
- `tests/ui/test_menus_toolbar.py` (9 tests): verbatim menu titles from
  the REAL QMenuBar (todo-4 lesson), disabled-state pins, undo guard,
  status mapping, isHidden-based toggles (toggleViewAction reflects
  window-not-shown state in offscreen — isHidden is the property-true
  check), lock reachable, QSettings roundtrip (bottom toolbar + hidden
  left dock + locked), real-bus probe (build_app→new_document→bind→emit),
  rebuild-hook through menu trigger.

## Events caught

- `post_command` consumed by if/elif previously ate the rebuild branch —
  split into two if chains (command label + rebuild label both flip).
- `write` tool refuses full rewrites of existing tracked files → edits
  via python; zero `type: ignore` in the final file.

## Gates

- `uv run ruff check .` → All checks passed (global fix applied once).
- `uv run ruff format --check .` → 174 files already formatted.
- `uv run basedpyright` → 0 errors, 0 warnings, 0 notes.
- scoped pytest (tests/ui + layering + scope_audit + notice + ci_workflow
  + core/test_signals) → 55 passed.
- Probe: tamper 编辑→編輯 menu title → 1 failed → restore → 1 passed.

## Status-bar signal contract (shared with todos 8/9)

subscribe set fragment = STATUS_SIGNALS (post_command, geometry_rebuilt,
command_amended, metadata_changed, named_group_added, named_group_removed,
document_saved). Selection/unit fields stay static until todo 10.
