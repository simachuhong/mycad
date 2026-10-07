# T9c 任务书：最小自测 demo 插件 + 真安装测试 + README 安全声明 + T9 收尾

你是 MyCAD 项目 T9c 片的执行代理。**第一动作：`cat` 本文件已完成。按 §5 清单机械执行，禁重新设计。**

## 0. 反停摆五纪律（违反=任务失败）

1. 禁写清单外文件；2. 单文件一次写 ≤100 行；3. 每回合一个小动作；4. 禁长推理；5. 遇阻输出 `BLOCKED: <原因>` 结束回合。

## 1. 白名单（仅允许创建/修改）

- 新建 `plugins_examples/mycad_plugin_demo/`（pyproject.toml + src/mycad_plugin_demo/__init__.py + README.md 短说明，独立包**不进主包依赖/wheel**）
- 新建 `tests/plugins/test_demo_module.py`（进程内）
- 新建 `tests/plugins/test_demo_installed.py`（唯一真安装测试）
- 修改 `README.md`（追加「插件与安全」短段）
- 追加 `.omo/evidence/task-9-phase0-mvp.md` §T9c + QA 段（T9 终稿）
- **禁改**：src/ 全部（app.py/plugins//commands//…）、tests/fixtures/、pyproject.toml、uv.lock、ci.yml（被 test_ci_workflow 锁定）；禁动 conftest；禁 git。

## 2. 上下文（勿重复勘察）

- 计划原文：`sed -n '400,428p' .omo/plans/phase0-mvp.md`（demo 插件/安装纪律/QA 段，C0 必读）。
- **已就绪**：T9a discovery/manifest + 夹具；T9b loader + app.py 接线（build_app(None)→EntryPointDiscoverer 真发现）。`cat src/mycad/app.py src/mycad/plugins/types.py` 精读。
- **安装链路（已实证，照抄命令）**：venv 由 uv 管理、pip 常缺→测试内先 `.venv/bin/python -m ensurepip --upgrade`（幂等）；安装 `sys.executable -m pip install -e <repo>/plugins_examples/mycad_plugin_demo --no-build-isolation --quiet`（hatchling+editables 已在主仓 dev extra，uv sync --extra dev 装齐）；卸载 `-m pip uninstall -y mycad-plugin-demo --quiet`。CI=uv sync --frozen --extra dev + uv run。
- 子进程运行测试脚本用 `[sys.executable, "-c", code]` + `cwd=仓库根` + env 继承（PYTHONPATH 无需设置：editable 安装使 demo 可导入；mycad 主包自身 editable 在 venv）。
- CommandContribution/FormatProvider/CliSyntax 构造签名见 types.py/formats/base.py（C0 精读）。

## 3. 钉死设计

### 3.1 demo 插件（plugins_examples/mycad_plugin_demo/）

- **pyproject.toml**：`[build-system] requires=["hatchling"] build-backend="hatchling.build"`；`[project] name="mycad-plugin-demo" version="0.1.0" description="Minimal MyCAD demo plugin" requires-python=">=3.12"`（**零 dependencies**——mycad 以运行环境存在，不入依赖）；`[project.entry-points."mycad.commands"] demo="mycad_plugin_demo:commands"`；`[project.entry-points."mycad.formats"] demo="mycad_plugin_demo:formats"`；`[tool.hatch.build.targets.wheel] packages=["src/mycad_plugin_demo"]`。
- **src/mycad_plugin_demo/__init__.py**（单文件，SPDX Apache-2.0 头 + docstring 注明同进程全信任安全模型）：
  - `manifest = {"id": "mycad-plugin-demo", "version": "0.1.0", "api_version": "1.0"}`（dict 形态）。
  - `DEMO_PING_SPEC = CommandSpec(id="demo.ping", version=1, summary_en="Ping the demo plugin", label_zh="演示：心跳", params_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False}, cli=CliSyntax(("ping",)), undo_compensation="history_replay")`（#round8-NB2 逐字）。
  - `class DemoPingHandler:` 属性 `command_id = "demo.ping"`；`def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> str: return "pong"`（无视 params；类本身即零参工厂）。
  - `def commands() -> list[CommandContribution]: return [CommandContribution(spec=DEMO_PING_SPEC, handler_factory=DemoPingHandler)]`。
  - `TXT_SUMMARY_PROVIDER = FormatProvider(name="TXT-SUMMARY", vendor="demo", priority=100, extensions=(".txt",), can_read=False, can_write=True, target="shape", _writer=_write_txt_summary)`；`def _write_txt_summary(geometry: ExportableKernel, path: Path) -> None:` 写一行体积摘要（`mass = geometry.mass_properties()`；文本形如 `solids=<n> volume=<v>`，UTF-8）。
  - `def formats() -> list[FormatProvider]: return [TXT_SUMMARY_PROVIDER]`。
  - 注意：demo 包 import mycad 符号（commands.spec/formats.base/plugins.types/core.handlers）——独立发行时假定宿主环境有 mycad。

### 3.2 `tests/plugins/test_demo_module.py`（进程内，≥8 例，无安装）

sys.path.insert(0, <repo>/plugins_examples/mycad_plugin_demo/src)（fixture+teardown 移除）：
- manifest 五字段逐字（dict 直取）；DEMO_PING_SPEC 七字段逐字断言（id/version/summary_en/label_zh/cli.verb_aliases==("ping",)/params_schema 深相等/undo_compensation）；params_schema additionalProperties is False。
- DemoPingHandler().handle({}, fake_ctx)=="pong"（fake ctx 任意对象——HandlerContext frozen 构造 (kernel, command_id)；直接传 MagicMock 禁用（仓库零 mock 依赖），用 SimpleNamespace 或真 HandlerContext(None, "demo.ping")——C0 勘察 HandlerContext 构造签名后选合法形态）。
- commands() 返恰一元素、spec is DEMO_PING_SPEC、handler_factory is DemoPingHandler。
- TXT_SUMMARY_PROVIDER 八字段逐字（name/vendor/priority/extensions==(".txt",)/can_read False/can_write True/target=="shape"/_writer 可调）。
- formats() 返恰一元素。
- **provider 字段完整性**（dataclasses.fields）：八字段名存在+can_read 为 bool+target ∈ {"shape","xcaf"}。
- 工厂返空 list 语义（插件可空注册——用闭包 [] 对照，证明 discovery 接受）可选例。

### 3.3 `tests/plugins/test_demo_installed.py`（唯一真安装纪律，≥6 例）

**结构**（全部 subprocess，避免污染测试进程 sys.modules/importlib 缓存）：
- module/class 级 fixture：session 顶端 ensurepip（`[sys.executable, "-m", "ensurepip", "--upgrade"]` returncode==0 否则 fail）→ pip install -e（同上命令，--no-build-isolation --quiet，cwd=repo 根）→ yield → teardown：pip uninstall -y --quiet + **残留断言**（`[sys.executable, "-c", "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('mycad_plugin_demo') is None else 1)"]` returncode==0，残留=失败）。
- 例：①安装后子进程 `from mycad.app import build_app; s = build_app(); ids = sorted(x.id for x in s.registry.search("demo.ping"))`——勘察 registry 查询 API（.search 或 list_by_category）后用合法调用，断言 demo.ping 在册+8 内置仍全在；②子进程 build_app→new_document(s)→bus.execute("demo.ping", {})=="pong"（handler_factory 生效）；③子进程 FormatResolver/registry resolve("x.txt") 返 FormatPort 结构（hasattr write）且 `.write(geometry, Path("/tmp/.../x.txt"))` 实写文件+内容含 "volume"；④`build_app()` 两次发现列表一致（确定性）；⑤卸载后（teardown 后独立子进程）build_app 发现恢复空（demo.ping 不在册）——本例置于独立 fixture 顺序或最后；⑥安装阶段失败即 fail（fixture 内断言）。
- **断言形态**：子进程 stdout 打印结果行（print(json.dumps(...))），主进程解析断言——禁在主进程 import demo。

### 3.4 README.md 追加段

文末「## 插件与安全」5-8 行：插件经 Python entry-points 同进程加载=**完全信任其作者**（无沙箱/签名/权限强制，ADR-003）；阶段 0 permissions 仅声明不强制；安装第三方插件前请审阅源码；demo 插件见 plugins_examples/。

### 3.5 evidence §T9c + QA

- §T9c：交付物/test_demo_module 与 installed 的测试设计（安装纪律 #round9-6/#round11-NB6：安装失败/卸载残留=失败）/README 段落。
- QA 段（T9 终稿）：①happy：安装 demo→子进程 build_app→execute demo.ping→"pong" 实录+plugins 发现列表等价输出（print 形式入档）；②failure：进程内 monkeypatch fake EP（future+bad 夹具）→核心命令仍全可用+warnings==2+id 正确；③卸载后列表恢复空。实测数据逐字入档。

## 4. 通用纪律

同 T9a/T9b：SPDX/basedpyright strict 零 ignore/ruff 全过/测试 docstring 禁守卫字面量/禁 git。demo 插件源码同样过 ruff+basedpyright（scoped 门点名）。

## 5. 执行清单

- C0：sed 取计划 400-428；`cat src/mycad/app.py src/mycad/plugins/types.py src/mycad/formats/base.py src/mycad/core/handlers.py src/mycad/commands/registry.py`；勘察 registry 查询 API（demo.ping 在册断言用）。
- C1：写 demo 插件 pyproject.toml。
- C2：写 src/mycad_plugin_demo/__init__.py（≤100 行一块）。
- C3：写 test_demo_module.py；跑绿（`.venv/bin/python -m pytest tests/plugins/test_demo_module.py -q`）。
- C4：写 test_demo_installed.py（fixture+例①②）；**真跑一次**验证安装链路（预期 2-3 分钟，pip 输出 --quiet）。
- C5：追加例③④⑤；跑绿。
- C6：README.md 追加段落。
- C7：scoped 四门：`.venv/bin/python -m pytest tests/plugins/ tests/app/ -q`（installed 测试含安装较慢，全量约 3-5 分钟）+ `.venv/bin/basedpyright plugins_examples/ tests/plugins/test_demo_module.py tests/plugins/test_demo_installed.py` + `.venv/bin/ruff check plugins_examples/ tests/plugins/ README.md`（README 由 ruff 忽略，仅 .py）+ `format --check` 同路径。
- C8：追加 evidence §T9c+QA 终稿（实测数据）。
- C9：输出 DoneClaim JSON（task="T9c"，含安装链路耗时/实测 QA 输出）。
