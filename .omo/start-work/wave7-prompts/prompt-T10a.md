# T10a 任务书：CLI 骨架 + REPL + 内建文档命令 + 批事务

你是 MyCAD 项目 T10a 片的执行代理。**点火已完成 cat 本文件。按 §5 清单机械执行，禁重新设计。**

## 0. 反停摆五纪律（违反=任务失败）

1. 禁写清单外文件；2. 单文件一次写 ≤100 行（cat > 首块 / cat >> 追加）；3. 每回合一个小动作；4. 禁长推理——设计已钉死；5. 遇阻输出 `BLOCKED: <原因>` 结束回合。

## 1. 白名单（仅允许创建/修改）

- 新建 `src/mycad/cli/__init__.py`、`src/mycad/cli/__main__.py`、`src/mycad/cli/session.py`
- 修改 `pyproject.toml`（**仅新增** `[project.scripts]` 表：`mycad = "mycad.cli.__main__:main"`——放 [project] 表之后、[dependency-groups] 之前，禁动其他任何行）
- 新建 `tests/cli/{__init__.py,test_repl.py,test_builtin.py,test_batch.py}`
- 新建 `.omo/evidence/task-10-phase0-mvp.md` §T10a
- **禁改**：src/mycad 其他一切（app/commands/core/formats/geom/plugins/builtin_commands/agent）、tests/ 既有文件；禁 git。

## 2. 上下文（勿重复勘察）

- 计划原文：`sed -n '429,463p' .omo/plans/phase0-mvp.md`（T10 规格，A0 必读）。
- **依赖面 API**：`app.build_app(discoverers=[]) -> AppServices(.registry/.kernel/.formats/.plugins)`；`app.new_document(services, *, confirmed_by=None) -> LoadedDocument(.document/.bus)`；grammar `parse_line(text, registry) -> (id, params)` / `to_cli(id, params, registry) -> str`；`core.open_document(path, *, registry, kernel, handlers) -> LoadedDocument`；`core.save_document(document, path)`；`Document.set_metadata`（未知键 ValidationError）+METADATA_KEYS；`bus.execute(id, params, confirmed_by="cli-local")`/`undo(n)`/`redo(n)`/`commands` property；`Plan(steps)`→`plan.confirm(actor)`→`bus.execute_batch(plan)`；`PlannedCommand(id, version, params, summary_en, affected_object)`；`AFFECTED_OBJECTS`（core/document.py，B.2 八值唯一权威，禁第二张表）；`services.formats.resolve(path) -> FormatPort`，`.write(kernel, path)`；`CliSyntaxError`（core/exceptions.py:105 已存在）；`CommandSpec.version/.summary_en`。
- pytest 用 `.venv/bin/python -m pytest`。tests/cli 需 `__init__.py`（SPDX 头+docstring，仓库惯例）。

## 3. 钉死设计

### 3.1 `__main__.py`

- `def main(argv: Sequence[str] | None = None) -> int`：argv None→sys.argv[1:]；空或 ["repl"]→REPL；["run", path, ...]→脚本（T10b 加 --json）；["help"]→帮助文本 stdout 退 0；未知子命令→stderr 单行 `unknown subcommand: <x>` 退 2；已知子命令缺参/格式错→2。stdout/stderr 入口处 `sys.stdout.reconfigure(encoding="utf-8")`（try/except AttributeError，非 tty 流可能无该方法）。模块尾 `if __name__ == "__main__": sys.exit(main())`。
- 帮助文本：子命令一行一列表（repl/run/validate/commands/plugins/help——validate/commands/plugins 标注 T10b/c 落地，help 文本先全列）。

### 3.2 `session.py`

- `class CliSession:` `__init__(self, services: AppServices) -> None`：持 `_services`、`_doc: LoadedDocument | None`、`_archive_path: Path | None`、`_batch: list[tuple[str, dict[str, object]]] | None`（None=批外）。
- `def run_repl(self) -> int`：`input_stream = sys.stdin`；tty（`sys.stdin.isatty()`）则每行前 `print("mycad> ", end="", flush=True)`；逐行 `self.execute_line(line)`；REPL 模式错误**不中断**（打印 stderr 单行继续）；quit/exit/EOF 返回累计码（无致命错=0）。readline 可选 import（`try: import readline  # noqa: F401 except ImportError: pass`）模块顶。
- `def run_script(self, path: Path) -> int`：文件不存在→stderr 单行退 2（**在校验任何内容之前**）；逐行执行；**首个错误即停**退 1；#注释/空行跳过；正常完=0。
- `def execute_line(self, line: str) -> int`（0/1/2，不抛）：
  1. strip；空/#→0。
  2. 内建命令分发（§3.3）。
  3. `begin-batch`：`_batch` 非 None（嵌套）→CliSyntaxError→2；否则 `_batch=[]`→0。
  4. `end-batch`：`_batch` None（未 begin）→2；空批（0 条）→CliSyntaxError 2（零步计划 minItems 1）；否则构造 Plan 并执行（§3.4）。
  5. 批内建模行：`parse_line`→ValidationError/CliSyntaxError→**批结构已破坏：整个脚本语义报错退 2 并清 `_batch`**？——**钉死：批内语法/校验错误按运行错误 1 处理，批中止**（`_batch=None`），错误行 stderr 单行；不执行批中任何已收集行（等价回滚语义——批尚未执行过任何命令）。
  6. 批外建模行：`parse_line`→`self._require_doc().bus.execute(id, params, confirmed_by="cli-local")`→异常→stderr 单行 `str(e)` 退 1。
- `_require_doc()`：`_doc` None→自动 new_document（REPL 惰性语义）。
- **退出码契约**：CLI 层用法错误（未知内建/参数缺失/文件不存在/嵌套 begin/未 begin 的 end/未闭合 EOF）=2，建模/执行错误=1。所有 stderr **单行**（`str(e)` 首行），禁 traceback 泄漏。

### 3.3 内建命令（CliSession 方法）

- `new`：`_doc = new_document(services)`；`_archive_path=None`；stdout `new document`。
- `open <path>`：扩展名非 .mc.json→2 stderr `open only supports .mc.json archives`（**先于任何 registry/文件访问**）；文件不存在→2；`open_document(path, registry=..., kernel=..., handlers=装配)`——handler 装配经 app 层：直接 `new_document` 后无法注入历史……**钉死**：`open_document` 需 handlers dict——复用 build_app 流程：`from mycad.app import _handler_map`（T9b 模块级函数）+`{**_handler_map(services.registry, services.plugins)}`；成功 `_archive_path=path` stdout `opened <path>`。
- `save [path]`：显式 path 扩展名非 .mc.json→2；省略且 `_archive_path` None→2 stderr `save requires a path for an unsaved document`；省略有 path→覆写；`save_document(doc.document, path)`（OSError 父目录等→1）；`_archive_path=path`；stdout `<path>`。
- `export <path>`：`services.formats.resolve(path)`（UnknownFormatError→1）→`.write(services.kernel, path)`（空几何 EmptyGeometryError→1）；stdout `<path>`。**导出不经 grammar/历史**。
- `meta <key>=<value>`：无参/缺 `=`→2；key 不在 METADATA_KEYS→ValidationError→1；value 去首尾引号；`doc.document.set_metadata(...)`；stdout `<key>=<value>`；**不进历史不置 confirmed_by**。
- `undo [n]`/`redo [n]`：n 默认 1；非正整数/超长 InvalidHistoryError→1。
- `history`：每行 `<ordinal>: <id> <to_cli(params)>  [confirmed_by=<actor>]`（confirmed_by None 省略方括号段；两个空格分隔）；无文档空输出。
- `help`：同 __main__ 帮助文本。
- `quit`/`exit`：停循环信号（返回特殊码交上层处理）。
- 未实现（T10b/c 占位分发到位即可，不响应）：validate/commands/plugins **不在 execute_line 内建集**（argv 层子命令）。

### 3.4 end-batch 执行

- 逐条收集项→`PlannedCommand(id=..., version=spec.version, params=params, summary_en=spec.summary_en, affected_object=AFFECTED_OBJECTS[id])`（spec=registry.get(id)；未知 id 在收集期已因 parse_line/registry 失败拦截）。
- `plan = Plan(steps)`→`plan.confirm(actor="cli-local")`→`self._require_doc().bus.execute_batch(plan)`。
- BatchRollbackError→stdout 打印回滚 ordinal 列表（`rolled back: <o1>, <o2>...`）+stderr 单行含 failed_ordinal/failed_command_id→1。
- 成功→`_batch=None`→0。批内历史 confirmed_by=="cli-local"（execute_batch 传入）。
- **未闭合检测**：run_script/run_repl 循环结束时 `_batch` 非 None→stderr 单行 `unterminated batch`→2（**批中任何行不执行**——已收集未执行天然满足）。

### 3.5 测试（tests/cli/，pytest+capsys+monkeypatch）

- **test_repl.py**（≥8 例）：main([]) 非 tty 喂 stdin 多行（monkeypatch sys.stdin=io.StringIO）；错误行后继续+后续命令成功；quit 停；exit 停；EOF 停；未知子命令 argv→2+stderr 单行；help→0；`mycad> ` 提示符 tty 分支（monkeypatch isatty True）断言输出含提示符。
- **test_builtin.py**（≥14 例）：new→执行建模行成功；meta 合法/未知键 1/缺=2/回显；save 省略路径无关联→2；save 显式+覆写+stdout 路径；save 非 .mc.json→2；open 非 .mc.json→2 且 resolve 未被调（monkeypatch services.formats.resolve spy——**构造 AppServices 手工装配**或 build_app([]) 后 replace）；open 不存在→2；open 真档（先 save 再 open）历史保留；export .step/.stl 真文件产出（真核）；export 未知扩展→1；undo/redo 参数与 InvalidHistoryError 1；history 文本形态+confirmed_by 段；新建 undo 空。
- **test_batch.py**（≥10 例）：begin→三建模行→end 执行（真核体积断言，法兰三命令体积 36794.3331588437 容差 1e-6——box(10,10,10) 先 new？**钉死用例**：begin→cylinder(r40 h8 mode new)→hole(d20 through_all)→hole_pattern(base d6 polar r25 count4)→end，断言体积+history 3 条+confirmed_by=="cli-local"）；批回滚（第 2 条参数非法）→1+stdout 回滚列表+stderr 含 failed_ordinal；嵌套 begin→2；未 begin end→2；未闭合（脚本尾）→2+批零执行；批内未知 id→1 批中止；REPL 批错误后继续；空批 end→2。
- 夹具：`build_app(discoverers=[])` 常用；stdin 喂行 helper。

## 4. 通用纪律

SPDX 两行头（Apache-2.0）新文件全部；basedpyright strict 零 ignore；ruff 全过；测试 docstring 禁守卫字面量；禁 git。

## 5. 执行清单

- A0：sed 取计划 429-463；`cat src/mycad/app.py`（_handler_map 签名核实）+`cat src/mycad/commands/grammar.py | head -60`（parse_line/to_cli 签名）。
- A1：写 cli/__init__.py+__main__.py（一块）。
- A2：写 session.py 块一（类+run_repl/run_script/execute_line 骨架+内建 new/open/save）。
- A3：session.py 块二（export/meta/undo/redo/history/help/批状态机+end-batch）。
- A4：pyproject 加 [project.scripts]。
- A5：写 test_repl.py；跑绿。
- A6：写 test_builtin.py（两块）；跑绿。
- A7：写 test_batch.py（两块）；跑绿。
- A8：scoped 四门：`.venv/bin/python -m pytest tests/cli/ -q` + `.venv/bin/basedpyright src/mycad/cli/ tests/cli/` + `.venv/bin/ruff check src/mycad/cli/ tests/cli/ pyproject.toml`（pyproject 不归 ruff，仅 .py）+ `format --check` 同 .py 路径。另：`.venv/bin/python -c "from mycad.cli.__main__ import main; print(main(['help']))"` 冒烟。
- A9：evidence §T10a（交付物/四门/设计决策：批内错误=1 批中止/未闭合=2/Lazy new/退出码映射表）。
- A10：DoneClaim JSON（{"task":"T10a","status":"DONE","deliverables":[...],"gates":{...},"deviations":[...],"notes":"..."}）。
