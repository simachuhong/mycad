# Task 10 — CLI：REPL + 脚本执行 + 批事务 + 退出码（Phase-0 MVP）

## §T10a CLI 骨架 + REPL + 内建文档命令 + 批事务（执行代理交付，2026-10-07）

### 交付物
- `src/mycad/cli/__init__.py`、`src/mycad/cli/__main__.py`（main 分发 + HELP_TEXT）、
  `src/mycad/cli/session.py`（CliSession：run_repl/run_script/execute_line + 11 内建
  + begin/end-batch 状态机 + 类级 _BUILTIN_HANDLERS 派发表）。
- `pyproject.toml` 仅新增 `[project.scripts]`：`mycad = "mycad.cli.__main__:main"`
  （置于 [project.optional-dependencies] 之后、[build-system] 之前；仓库无
  [dependency-groups] 表，故以 [build-system] 为后界）。
- `tests/cli/{__init__,test_repl,test_builtin,test_batch}.py`：9+16+11 = 36 例。

### scoped 四门（A8 复跑通过）
- `.venv/bin/python -m pytest tests/cli/ -q` → **36 passed**。
- `.venv/bin/basedpyright src/mycad/cli/ tests/cli/` → **0 errors, 0 warnings, 0 notes**（零 ignore）。
- `.venv/bin/ruff check src/mycad/cli/ tests/cli/` → All checks passed；
  `ruff format --check` 同路径 → 7 files already formatted。
- 冒烟：`from mycad.cli.__main__ import main; main(["help"])` → 打印子命令表，rc=0。

### 设计决策（钉死项的落地记录）
1. **批内错误 = 1 批中止**：批内 parse_line 失败（CliSyntaxError/UnknownCommandError）
   → `_batch=None`、错误行 stderr 单行、退 1；已收集行从未执行（等价回滚语义）。
   参数级 ValidationError 不在收集期拦截——留给 end-batch 的 execute_batch →
   BatchRollbackError → 1（stdout `rolled back: <历史 ordinal 列表>`、stderr 单行
   含 failed_ordinal/failed_command_id，即 str(BatchRollbackError) 原文）。
2. **未闭合批 = 2**：run_repl/run_script 循环结束（EOF/quit）时 `_batch` 非 None →
   stderr 单行 `unterminated batch`、退 2，批中行零执行（天然满足：从未执行过）。
3. **Lazy new**：`_require_doc()` 在首个建模/保存需求时惰性 `new_document`（REPL 语义）；
   显式 `new` 额外重置 `_archive_path=None`。
4. **退出码映射表**：0 成功；2 = CLI 层用法错误（未知子命令/内建参数缺失或格式错/
   run·open 文件不存在/open·save 扩展名非 .mc.json/嵌套 begin/未 begin 的 end/空批 end/
   未闭合批）；1 = 运行错误（未知建模 id/参数 ValidationError/几何错误/导出
   UnknownFormatError·EmptyGeometryError·OSError/meta 未知键/undo·redo 非正整数与
   InvalidHistoryError/批回滚）。REPL 模式错误不中断循环，会话码取各 行码最大值
   （无致命错=0）；脚本模式首错即停。
5. **open 装配**：`_cmd_open` 复用 app 层 `_handler_map(registry, plugins)` 构造
   handlers dict 后调 `core.open_document`（先扩展名门、再存在性门，均先于任何
   registry/文件访问——resolver spy 测试证明 provider 通道未被触碰）。
6. **法兰钉死用例**：begin→cylinder(r40 h8 new)→hole(d20 through_all)→hole-pattern
   (d6 polar r25×4)→end，体积 = π·8·(40²−10²−4·3²) ≈ 36794.3331588437（abs=1e-6）、
   history 3 条、全部 `[confirmed_by=cli-local]`；`rolled back` 的 ordinal 为批前
   历史长度起的真实命令 ordinal（base+i）。

### 偏差记录
- D1: `_handler_map` 为 mycad.app 模块私有名，`from mycad.app import _handler_map`
  在 basedpyright strict 下触发 reportPrivateUsage；改为 `import mycad.app` +
  `cast("Callable[...]", getattr(mycad.app, "_handler_map"))`（# noqa: B009，bus.py
  同型先例）——零 ignore、零逻辑复制，语义与任务书钉死的"复用 build_app 流程"一致。
- D2: `readline` 可选导入按钉死块落位；因 basedpyright reportUnusedImport 不认
  `# noqa: F401`，try 块内补 `assert readline` 保留引用（无行为影响）。
- D3: validate/commands/plugins 三个 argv 子命令占位：帮助文本已全列（标注 T10b/c），
  分发 slots 落位但报 `<sub>: not implemented yet` 退 2（"占位分发到位即可，不响应"
  的确定行为；T10b/c 替换分支体）。
- D4: pyproject 插入点后界为 [build-system]（仓库无 [dependency-groups] 表）。

## §T10b run --json + validate + history --json（主会话直接实现，2026-10-11）

### 交付物
- 新建 `src/mycad/cli/plans.py`：附录 B.1 唯一校验器 `validate_plan_dict` / `load_plan_file`
  （`run --json` 与 `validate .json` 共用；错误带 `steps[i].params` / `steps[i].affected_object`
  等定位前缀；plan_id 缺省 `uuid4().hex`，显式值须 `^[0-9a-f]{32}$`）。
- `session.py`：`run_json`（B.3 六步：独立新文档 → Plan.confirm("cli-local") → 一次
  execute_batch → metadata 存在即写入 → outputs 导出，三键全缺省时按计划 stem 产三件）、
  `validate_file`（.json/.txt，其他扩展名 2）、`history --json`（`asdict` 生成，字段与存档命令
  条目一致，amendments 仅非空时出现）。
- `__main__.py`：`run --json <file>`、`validate <file>` 分发；commands/plugins 仍为 T10c 占位。
- 测试：`tests/cli/{_flange,test_run_json,test_validate,test_history}.py`，新增 38 例。

### 门禁
- 全量：pytest 752 passed（沙箱外；沙箱内 test_demo_installed 因 .venv 只读报错，属环境）/
  ruff check 全过 / 158 files formatted / basedpyright 0-0-0。
- 真实 CLI 冒烟：`mycad validate` → `valid: plan 3 step(s)` rc=0；`mycad run --json` → rc=0，
  产出 step 24507B / stl 152084B / mc.json 1665B；坏 JSON → 单行 `invalid JSON: ...` rc=1。
- 篡改探针：plans.py 的 affected_object 检查改为 `if False:` → 1 failed（红）→ 还原 → 全绿。

### 设计决策 / 偏差
- D5: 批结构判定抽为 `_batch_structure_error`，begin/end-batch 执行路径与 validate 共用
  （T10a 文案不变，既有测试全绿）；回滚行打印抽为 `_print_rollback`，run_json 失败时同样
  输出 `rolled back: <ordinals>`。
- D6: validate .txt 的内建行语法错误按 run 时的用法错误归类退 2（任务书草稿写 1，与
  "退出码归类与 run 相同"的计划原文冲突，以计划为准）；undo/redo 的 n 不做静态检查。
- D7: `history` 非法参数文案由 `history takes no arguments` 改为 `usage: history [--json]`。
