# T10c 任务书：commands/plugins 子命令 + QA happy/failure + evidence 终稿

你是 MyCAD 项目 T10c 片的执行代理。**点火已完成 cat 本文件。按 §5 清单机械执行，禁重新设计。前置：T10a/T10b 已交付并采信（cli 骨架+plans.py+七测试文件在盘）。**

## 0. 反停摆五纪律（违反=任务失败）

1. 禁写清单外文件；2. 单文件一次写 ≤100 行（cat > 首块 / cat >> 追加）；3. 每回合一个小动作；4. 禁长推理——设计已钉死；5. 遇阻输出 `BLOCKED: <原因>` 结束回合。

## 1. 白名单（仅允许创建/修改）

- 修改 `src/mycad/cli/__main__.py`（仅：新增 `commands`/`plugins` 子命令分发）
- 修改 `src/mycad/cli/session.py`（仅：追加 `list_commands(as_json: bool)`/`list_plugins()` 两方法；禁动其他）
- 新建 `tests/cli/{test_commands_plugins.py,test_qa.py}`
- 追加 `.omo/evidence/task-10-phase0-mvp.md` §T10c+终验段
- **禁改**：src/mycad 其他一切、tests/cli 既有七文件；禁 git。

## 2. 上下文（勿重复勘察）

- 计划原文：`sed -n '429,463p' .omo/plans/phase0-mvp.md`（T10 规格 QA 段）——A0 必读。
- **依赖面 API**：`build_app(discoverers=[])`（禁用发现→恰 8 内置）/`build_app(None)`（真发现）；`CommandSpec.cli.verb_aliases[0]`/.id/.summary_en/.label_zh；`registry.list_by_category() -> dict[str, list[CommandSpec]]`（无 __iter__）；`PluginManager.loaded()`/`.skipped() -> tuple[tuple[str, str], ...]`（**A0 勘察 src/mycad/plugins/manager.py 确认 loaded() 返回形态**——含 manifest 与贡献计数来源）；`get_args(WARNING_REASON)`（plugins/types.py，六码）；demo 插件真安装链路（T9c test_demo_installed.py 模式：ensurepip→pip install -e plugins_examples/mycad_plugin_demo --no-build-isolation --quiet→断言→pip uninstall -y）；`open_document(path, *, registry, kernel, handlers)`；法兰三步体积 36794.3331588437 容差 1e-6。
- pytest 用 `.venv/bin/python -m pytest`。

## 3. 钉死设计

### 3.1 commands 子命令（argv ["commands"] 或 ["commands", "--json"]）

- **计数环境隔离写死**：`list_commands` 内部 `build_app(discoverers=[])` 全新 services（不接收外部 services——确保 CI editable 装 demo 后仍恰 8）。
- 收集：8 内置 spec→`(verb=spec.cli.verb_aliases[0], id, summary_en, label_zh)` 按 verb 字典序。
- 无 --json：stdout 每行制表符三列 `<verb>\t<id>\t<summary_en>`；恰 8 行。
- --json：一行 `{"commands": [{"verb": ..., "id": ..., "summary_en": ..., "label_zh": ...}]}` 恰四键按 verb 升序；顶层恰 commands；`ensure_ascii=False`。
- 退出码恒 0。

### 3.2 plugins 子命令（argv ["plugins"]）

- `services = build_app(None)`（真发现——None→默认 EntryPointDiscoverer()）。
- 每个已加载插件一行：`loaded: <manifest.id> v<manifest.version> api=<manifest.api_version> commands=<n> formats=<n>`（n=该插件贡献数；形态以 A0 勘察 manager 为准，缺计数则从 command_contributions()/format_providers() 按 distribution 归属统计——**以勘察实况写，evidence 记录**）。
- 每个跳过一行：`skipped: <distribution-name> reason=<code>`（code ∈ WARNING_REASONS 六值）。
- 退出码恒 0（跳过不构成错误）；无插件→零行输出。

### 3.3 测试

- **test_commands_plugins.py**（≥10 例）：
  - commands（进程内 main(["commands"])）：恰 8 行三列制表符；verb 字典序（box<cut<cylinder<extrude<fillet<hole<hole-pattern<revolve）；--json 顶层键集恰 {commands}+8 元素四键+verb 升序+label_zh 中文非 ASCII 转义（ensure_ascii=False 断言中文字符在场）；退出码 0。
  - **装 demo 环境 9 行**：ensurepip+pip install -e demo→子进程或进程内 main(["commands"])？——**钉死进程内**（安装后当前进程 entry_points 已可发现：`build_app(None)` 才真发现，但 commands 用 build_app([]) 恰 8！**9 行断言改用在装 demo 环境跑 `main(["plugins"])` loaded 行含 demo.ping+TXT-SUMMARY**；commands 恒 8 是规格钉死语义）→uninstall。若进程内 importlib.metadata 缓存导致发现失效→改子进程（`sys.executable -c` 调 main 打印），evidence 记录选型。
  - plugins：monkeypatch `importlib.metadata.entry_points`（T9 夹具 tests/fixtures/plugins/mycad_plugin_manifest_dict 经 sys.path）→main(["plugins"])→stdout 含 `loaded: ...` 行；future 夹具→`skipped: ... reason=incompatible-api`；坏夹具→manifest-error 行；退出码恒 0；无插件环境（不 patch，当前干净）→零行 0。
- **test_qa.py**（≥7 例，QA happy+failure 矩阵）：
  - **happy**（stdin 全序列，monkeypatch sys.stdin）：`new`→`begin-batch`→`cylinder radius=40 height=8 center=[0,0,0] mode=new`→`hole diameter=20 depth=through_all ...`（法兰参数形态以 tests/cli/test_batch.py T10a 既有批用例为准抄参数）→`hole-pattern ... count=4 radius=25`→`end-batch`→`export <tmp>/flange.step`→`export <tmp>/flange.stl`→`save <tmp>/flange.mc.json`→`history --json`→`undo 3`→`save <tmp>/after_undo.mc.json`→`quit`。断言：退出 0；flange.step>10240B；history json 3 条 confirmed_by=="cli-local"；读回 flange.mc.json（open_document+build_app([]) services）→mass_properties.volume==36794.3331588437 容差 1e-6+solid_count==1+历史 3 条；读回 after_undo.mc.json→commands 空+体积 0.0（undo 3 批回滚到空文档）。
  - **failure**：未知子命令 argv→2；`open /nonexistent.mc.json`→2；脚本 begin→cylinder→hole 非法参数→end→批回滚退 1+stdout 回滚列表+stderr 含 failed_ordinal；脚本未知建模 id 行→1；`run --json` 损坏 JSON 文件→1 单行错误非 traceback（断言 stderr 不含 "Traceback"）。

### 3.4 evidence 终稿

§T10c+终验段：交付物清单/四门计数/QA happy 实测数据（体积/字节数/两档读回断言值逐字）/failure 矩阵 stderr 文案+退出码表/9 行环境选型记录/偏离 D 列表。

## 4. 通用纪律

SPDX 两行头；basedpyright strict 零 ignore；ruff 全过；测试 docstring 禁守卫字面量；禁 git。

## 5. 执行清单

- A0：sed 取计划 429-463；cat src/mycad/plugins/manager.py（loaded/skipped/贡献计数形态）；cat tests/cli/test_batch.py（法兰参数行形态）；cat tests/plugins/conftest.py（夹具 sys.path 模式）。
- A1：session.py 追加 list_commands/list_plugins；__main__.py 加两分发。
- A2：写 test_commands_plugins.py（两块）；跑绿。
- A3：写 test_qa.py happy（stdin 序列+读回断言）；跑绿。
- A4：写 test_qa.py failure 矩阵；跑绿。
- A5：scoped 四门：`.venv/bin/python -m pytest tests/cli/ -q`（全目录）+ `.venv/bin/basedpyright src/mycad/cli/ tests/cli/` + `.venv/bin/ruff check src/mycad/cli/ tests/cli/` + `format --check`。
- A6：evidence §T10c+终验段。
- A7：DoneClaim JSON（{"task":"T10c","status":"DONE","deliverables":[...],"gates":{...},"deviations":[...],"notes":"..."}）。
