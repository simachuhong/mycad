# 证据：task 8 phase1-desktop-shell（文档生命周期 + 未保存拦截）

- 提交：`feat(ui): document lifecycle with unsaved-change guard`
- 变更丽面：`src/mycad/ui/main_window.py`（新增槽与守卫）、`src/mycad/app.py`（公开转发）、`tests/ui/test_document_lifecycle.py`（新，10 测试）、`tests/ui/test_menus_toolbar.py`（五活两禁更新）

## 实现摘要
- 新建 = `app.new_document()`；打开 = persistence `open_document`；保存/另存 = `save_document`；导出 = formats 既有 provider（`formats.resolve(path).write(kernel, path)`，初稿单菜单项「导出（STEP/STL）」用 QFileDialog 过滤器分流——计划「两动作」→ 两格式目标（evidence 偏差①））。
- dirty = 并集信号订阅（STATUS_SIGNALS 全集在 bind_document 重订；单命令/批执行只发 pre/post_command、undo/redo/重放/回滚只发 geometry_rebuilt——两族缺一漏）。
- 保存成功显式 `document.mark_clean()`（persistence 不清脏）。
- 三选拦截：`_confirm_unsaved_changes`（dirty→`_ask_save_dialog` QMessageBox Accept/Destructive/Reject 判别 clickedButton）→ closeEvent False → `event.ignore()`。
- 单文档替换：`_replace_document` 重绑；`bind_document` 首行清 `_signal_adapters`（旧总线弱引用自然断链）。
- handlers 装配同源：CLI 用 getattr 私有桥；UI 禁同桥（reportPrivateUsage 跨模块）→ `mycad/app.py` 增公共转发 `handlers_for(services)`（evidence 偏差②：装配真源仍唯一 `app._handler_map`，仅多一个公开 re-export；CLI 不动）。

## 关键修复史（勿重犯）
1. `Document.is_dirty` 是 **@property 而非方法**（document.py:166-170）——`is_dirty()` 调用报 "bool 不可调用"。
2. teardoop 挂死根因（faulthandler 栈实证）：pytest-qt `_close_widgets` → `closeEvent` → 脏窗口走**真实** `_ask_save_dialog` → offscreen QMessageBox.exec 阻塞整进程。兜底 = 测试模块 autouse patch `_ask_save_dialog→discard`（注册最先/还原最后，单测自打 patch 先解不影响语义）。
3. `MainWindow._loaded` 私有访问 22 处 → 新增公共只读 `loaded_document() -> LoadedDocument | None`（getattr+cast 两路皆被 pyright 解析拒绝；tests 用 `_loaded_of`/`_bound` helper 窄化）。
4. reopen 期望面：重放回填默认（center/mode），`feature.box` 参数为 5 键。

## 红绿探针（计划要求，dtamper→red→restore→green）
- 篡改 `_confirm_unsaved_changes` 条件（`not is_dirty` → `is_dirty`）：`2 failed, 1 passed`（RED 闭环）。
- 还原：`3 passed`（GREEN 闭环）。

## 验证
- scoped：`QT_QPA_PLATFORM=offscreen pytest tests/ui tests/test_layering.py tests/test_scope_audit.py tests/core/test_signals.py -q` = **74 passed**（含 lifecycle 10）。
- `ruff check src tests` 全过；`ruff format --check src tests` 165 files 0 修；`basedpyright src/mycad/app.py src/mycad/ui tests/ui` = **0 errors / 0 warnings / 0 notes**。
- 无新增 type:ignore/pyright:ignore（layering 抑制扫描在 scoped 内）。
