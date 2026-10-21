# 证据：task 11 phase1-desktop-shell（底栏 CLI Tab，与 session 同源）

- 提交：`feat(ui): CLI tab reusing session dispatch for parity`
- 变更面：`src/mycad/cli/session.py`（CliSession 纯函数化）、`src/mycad/ui/cli_tab.py`（新），
  `src/mycad/ui/main_window.py`（CLI/Chat 底栏 TabWidget + 回调接线）、`src/mycad/ui/viewport.py`
  （重构窗口绕过 `QTimer.singleShot` 改成持有化 `QTimer`，`dispose()` 主动 `stop()`）、
  `tests/ui/test_cli_tab.py`（新，9 测试）。

## 一致性（搓准）
- CliSession.__init__ 现接受 `doc` / `on_replace_doc` / `messages` 关键字参数；
  `_replace_doc()` 是唯一文档替换入口（`_cmd_new` / `_cmd_open` 均改走此端口）——lazy 馋试
  同样经由它，与 GUI 打包（回档、脏态复位、树/视口刷新）打包一致。
- 新增 `_say（消息收集器）` 替换全部 18 处 `print(...)`；sink=None 走原样打印（headless CLI
  的 REPL / script 驱动外壳仍走终端 print，批次状态跑在同一持久 CliSession 上，保证
  tests/cli 全绿）。
- 纯函数 `execute_line(line, *, loaded, services, on_replace_doc) -> tuple[int, list[str]]`：
  每次调用新起一个 `CliSession`（批次跨度不持久），带 `messages` 收集器生成所有反馈消息，
  rc 沿用 0/1/2 与 `_QUIT_REQUESTED` 两套常量；单标签窗口所传 `on_replace_doc` 即落到
  `_on_cli_document_replace`（回填 `_replace_document(loaded, None)`）。
- `run_repl` 与 `run_script` 的提示符（"mycad> "）保持原生 print、不经收集器（提示符是
  交互外壳输出而非命令反馈）。

## 同源文案（对拍）
- CLI tab 的 `_dispatch_line` 短路 `quit`/`exit` → 返回 rc == `QUIT_SENTINEL`（-1），面板输出
  `repr(QUIT_SENTINEL)` + " (hint: use File > Close to exit the app)"，不关窗口；
  其余行直接使用 headless 对同 line 的 `execute_line`，文件逐字复制、只有消息前缀（即
  输出面板顶部提示符 `">>> "`）。 详细输出与窗口 binding 一致，另存副作用只经
  CliTab 自有调用 `save_document` 走主窗口 todo 8 的持久化封装。

## 测试矩阵（9 用例）
tests/ui/test_cli_tab.py：
1. parity `new`：`cliTab.dispatch_line("new")` 输出面板文本 == headless `execute_line("new")` 结果。
2. parity 负向：未知命令 → 两条路径同为错误文案（stderr 原样入 sink）。
3. dispatch 纯输出（capsys 断言 0 字节落出）。
4. lazy 文件：首条建模行触发 `on_replace_doc` 回调一次，LoadedDocument 正确换系。
5. 批次跨界不持久（两条独立 execute_line 调用，资 `end-batch` rc==1）。
6. CLI tab 触发后 window.loaded 文档更新（装载回路，`bind_document` 接通）。
7. 底栏含「CLI」「Chat」两个 tab 项。
8. quit sentinel：rc == -1，不关窗口。
9. open 回路：`CliSession.save_document` 后 `dispatch_line(f"open {path}")` 重新绑定主窗口文档。

## 范围审计
- 无类型压制（零 `# type: ignore` / pyright-ignore）；基于（basedpyright）strict 下
  0 errors, 0 warnings, 0 notes。
- 独立性：ui/cli_tab.py 直接复用 session 语义，`from mycad.cli.session import QUIT_SENTINEL,
  LoadedDocument, execute_line`，与 `tests/ui/test_cli_tab.py` 同路（不必复制解析器）。

## 台阶
- 沿用 todo9 的 offscreen 潜力证实 Qt non-GL widget（纯 QtWidgets）测试可行性。

## 残余
- 纯函数 execute_line 不持久批次（跨行批次差导入差异：REPL 保持 `CliSession.execute_line`
  持久批次，与原来一致）；GUI 若需跨行批次，使用单标签面板内独立 dispatch 会话流或后并入
  todo 12 卡片流。
