# Task 9 — 插件扩展缝（entry-point discovery + manifest/api 门控 + demo 插件）

## §T9a manifest 解析 + entry-point 发现（进程内夹具）

- 执行者：T9a（`.omo/start-work/wave6-prompts/prompt-T9a.md`，逐字执行）+ 编排方收尾
- 日期：2026-10-07
- 采信方式：实例 ses_eec1bcc37ffeRnX5moGwxRZqbv 于 09:24:31 死于 5h 配额墙（与主编排同一中断事件，61 msgs）。A1-A11 交付完整落盘（src+夹具+测试+锁更新），A12 evidence/A13 DoneClaim 缺失——编排方复跑 scoped 四门全绿后采信（先例 T8a/T6b/T7a）。

### 交付物

- `src/mycad/plugins/manifest.py`（143L）— `resolve_manifest(module) -> tuple[PluginManifest | None, str | None]`：三形态归一（dict/零参 callable/实例）；五键校验（缺/多/类型错/id 非法 `^[a-z0-9_.-]+$`→manifest-error）；api 门（主版本 int(split(".",1)[0])≠CURRENT_API_MAJOR 或不可解析→incompatible-api）；三码经 `get_args(WARNING_REASON)[0/1/2]` 派生（_MISSING_MANIFEST/_DAMAGED_MANIFEST/_API_MISMATCH），零散落字符串。
- `src/mycad/plugins/discovery.py`（200L）— `EntryPointDiscoverer(groups=("mycad.commands","mycad.formats"))`：`_distribution_name(ep)`（ep.dist 非 None 且 metadata["Name"] 非空→用之；否则 fallback ep.module——手造 EP 无 dist，真实 EP 用 dist 名）；按 module memoize resolve_manifest（callable 只调一次）；entry 契约组隔离求值（零参 callable→恰调一次→list→逐元素 isinstance；非 callable/非 list/类型错/异常→该组跳过+load-error=get_args[5]）；同 distribution 合并（commands/formats 分列、entrypoint 去重排序 `<group>:<module>:<attr>`、warnings 合并）；按 distribution_name 排序返回 tuple。
- `src/mycad/plugins/__init__.py` — 再导出 += EntryPointDiscoverer（七名）。
- `tests/fixtures/plugins/` 七棵夹具树（每树 pyproject.toml 文档价值+模块源码，纯进程内禁 pip）：manifest_dict（dict 五字段）/manifest_callable（callable+模块计数器）/future（api 9.9）/bad（missing_attr/bad_missing/bad_extra/bad_types/bad_id）/matrix（api_1_0/api_1_5/api_2_0/api_v1/api_abc）/conflict（feature.box 冲断+.txt provider，T9b 用）/formats（empty_factory/raise_factory/single）。
- `tests/plugins/conftest.py`（39L）— sys.path 注入 tests/fixtures/plugins + teardown 移除。
- `tests/plugins/test_manifest.py`（225L，22 例）+ `tests/plugins/test_discovery.py`（335L，22 例，monkeypatch importlib.metadata.entry_points 手造 EP）。
- `tests/plugins/test_agent.py` — 公开面锁更新：七名（+EntryPointDiscoverer）；PLUGINS_SUBMODULE_ARTIFACTS={types,manager,discovery,manifest,loader}（预列 T9b loader 免疫 import 顺序非确定性）。

### 四门（scoped，编排方复跑）

1. `-m pytest tests/plugins/ -q` → **72 passed**（T7b 基线 18+净增 54）。
2. `-m basedpyright src/mycad/plugins/ tests/plugins/` → **0/0/0**；`tests/fixtures/plugins/` 单独扫 → **0/0/0**。
3. `-m ruff check src/mycad/plugins/ tests/plugins/ tests/fixtures/` → 全过。
4. `-m ruff format --check` 同路径 → 32 files already formatted。

### Deviations

- **D1（_distribution_name fallback）**：py3.12.3 EntryPoint 不可构造注入 .dist（immutable），手造 EP 恒 None→回退 ep.module 作 distribution 名（同模块两组→同 key→合并成立；真实 EP 用 dist.metadata["Name"]）。运行时实证于 2026-10-07。
- **D2（六码派生形态）**：manifest.py 以 get_args(WARNING_REASON)[0/1/2] 命名常量、discovery.py 以 [5] 取 load-error——规避 AST 六码字面量守卫（#round9-5），语义与 types.py Literal 源序锁定。
- **D3（evidence 由编排方补写）**：子代理死于 A12 前回合；四门数据为编排方复跑实测。
- **D4（夹具 pyproject 不参与构建）**：仅声明 entry-points 作文档；测试用手造 EntryPoint 直接构造，零 pip、零打包（#round10-NB3 纯进程内）。

## §T9b 插件装载器 + app.py 真接线（冲突隔离/兑底/信号钩）

- 执行者：T9b（`.omo/start-work/wave6-prompts/prompt-T9b.md`，逐字执行）
- 日期：2026-10-07

### 交付物

- `src/mycad/plugins/loader.py`（89L）— `register_plugins(registry, formats_registry, discovered) -> tuple[DiscoveredPlugin, ...]`：逐插件逐条注册；CommandConflictError→跳过该命令条目（不跳整插件其余命令）+command-conflict 码；ProviderConflictError→跳过该 provider 条目+provider-conflict 码；每插件经 `dataclasses.replace` 生成新 DiscoveredPlugin（存活 commands/formats + warnings 原码∪新码去重保序 `dict.fromkeys`）；纯函数（入参不可变）。两码经 `get_args(WARNING_REASON)[3/4]` 派生（承 T7b/T9a D2 模式，零散落字面量）。`__all__=["register_plugins"]`。
- `src/mycad/app.py`（92L→112L，仅两处接线）—
  1. line 59 替换：`del discoverers` → None→`(EntryPointDiscoverer(),)` 默认真发现；显式序列→`tuple(discoverers)`（`[]`=空发现保持）；多 discoverer 串联（扁平化拼接各 `discover()` 结果）→ `register_plugins(registry, formats, discovered)` → `PluginManager(loaded)`；内置 8 命令先注册（插件撞内置→装载期跳过）。
  2. handler 装配抽取：模块级 `_handler_map(registry, plugins) -> dict[str, CommandHandler]`——内置每 spec 一个 `BuiltinModelingHandler(spec.id)`（保持原 8 命令装配语义）+ 插件贡献 factory 非 None→`factory()`、**None→`BuiltinModelingHandler(contribution.spec.id)` 兑底**（新 else 分支）；`new_document` 改调 `_handler_map(services.registry, services.plugins)`（每次 new_document 现装配，语义不变）。AppServices 四字段、其余骨架不动。
- `tests/plugins/test_loader.py`（336L，14 例 ≥ 13）：例 1-6 装载器（冲突命令跳过+内置保留 / provider 冲突跳条目+直注册断言 / 不跳整插件 / 零 warning / 同码去重 / 可交 PluginManager）；例 7-9 `_handler_map`（None 兑底 / factory 优先 is 断言 / 内置恰 8 键）；例 10-12 build_app 接线（None→真发现 monkeypatch 计数 1+8 命令 / 显式 []→计数 0【任务书例 10 拆两例】/ 多 discoverer 串联 / 纯函数性）；例 13 信号钩异常隔离集成（真 build_app([])+new_document，pre_command 抛异常回调+计数回调，`pytest.warns(RuntimeWarning)` 下 execute 成功+另一回调收到+历史 1 条）。

### 四门（scoped，T9b 实测）

1. `-m pytest tests/plugins/ tests/app/ tests/builtin_commands/ -q` → **166 passed**（loader 净增 14；app/builtin_commands 无回归）。
2. `-m basedpyright src/mycad/plugins/loader.py src/mycad/app.py tests/plugins/test_loader.py` → **0/0/0**。
3. `-m ruff check src/mycad/plugins/ src/mycad/app.py tests/plugins/` → All checks passed。
4. `-m ruff format --check` 同路径 → 15 files already formatted。
- **篡改探针**：改坏 loader 冲突码索引（[3]→[4]）→ 3 failed；还原 → 14 passed（红→绿闭环）。

### Deviations / 设计说明

- **D5（warnings 携码不携 name/vendor——解释性偏离）**：规格「warning 含两 provider name/vendor」经 **ProviderConflictError 字段**满足：`register` 抛错携带 `extension`+`provider1/provider2` (name, vendor) 元组（formats/registry.py T8a 既有），测试 2 直注册断言 `extension==".txt"`、`provider1==("TXT-PRE","t9b")`、`provider2==("TXT-FIXTURE","fixture")`。warnings tuple 只携六码系 #round9-5 硬约束（reason 逐字取自 WARNING_REASONS，禁新造字符串），两要求以「错误对象携细节、警告码走契约」分层并存。
- **D6（多 discoverer 串联实现形态）**：任务书伪码 `tuple(d.discover() for d in discoverers)` 为元组之元组，与 `register_plugins(discovered: Sequence[DiscoveredPlugin])` 签名不符；实现为扁平化拼接（`discovered += tuple(discoverer.discover())`），例 11（两 fake discoverer 各一插件→PluginManager 持两者）锁定该语义。
- **D7（`_handler_map` 测试访问经 getattr 桥）**：直 import 私有名触发 basedpyright reportPrivateUsage，而 pyright-ignore 全仓禁用（tests/test_layering.py 针锁定）——测试侧用仓库既定桥 `cast(..., getattr(app_module, "_handler_map"))  # noqa: B009`（同 test_persistence.py `_REGISTRY` / bus.py 四桥模式）。
- **D8（任务书例 10 拆两例）**：「None→真发现」与「显式 []→不调 discoverer」拆为独立两测试（各自 monkeypatch 计数断言更清晰），总数 14 ≥ 13。
- **B2 无红相说明**：B1 按钉死设计一次成稿，例 1-6 首跑即绿（任务书 B2「跑红」预期未出现红相；B3 为确认跑）。测试敏感性由 B7 篡改探针（3 failed）反向证实。

## §T9c 最小自测 demo 插件 + 真安装测试 + README 安全声明（T9 收尾）

- 执行者：T9c（`.omo/start-work/wave6-prompts/prompt-T9c.md`，逐字执行）
- 日期：2026-10-07

### 交付物

- `plugins_examples/mycad_plugin_demo/pyproject.toml` — 独立发行（零 dependencies；不入主包/wheel）：hatchling backend；`[project] name="mycad-plugin-demo" version="0.1.0" requires-python=">=3.12"`；entry-points `mycad.commands` demo=`mycad_plugin_demo:commands` + `mycad.formats` demo=`mycad_plugin_demo:formats`；`[tool.hatch.build.targets.wheel] packages=["src/mycad_plugin_demo"]`。
- `plugins_examples/mycad_plugin_demo/src/mycad_plugin_demo/__init__.py`（99L）— SPDX+docstring 注明同进程全信任安全模型；`manifest` dict 三键（id/version/api_version="1.0"）；`DEMO_PING_SPEC` 七字段 #round8-NB2 逐字（params_schema 零参 additionalProperties=False）；`DemoPingHandler`（command_id="demo.ping"，handle 无视 params/ctx 返 "pong"，类本身即零参工厂）；`commands()` 返单元素 CommandContribution(spec is DEMO_PING_SPEC, handler_factory is DemoPingHandler)；`_write_txt_summary`（mass_properties()→`solids=<n> volume=<v>` 一行 UTF-8）；`TXT_SUMMARY_PROVIDER` 八字段逐字（TXT-SUMMARY/demo/100/(".txt",)/False/True/"shape"）；`formats()` 返单元素 list。
- `tests/plugins/test_demo_module.py`（9 例，进程内零安装）— fixture sys.path 注入 `plugins_examples/mycad_plugin_demo/src`+teardown 移除，`importlib.import_module` 动态导入（demo 是独立发行、不进主 import 图；同 T9a 夹具模式）。例：manifest dict 直取逐字+键集恰三；spec 七字段逐字；params_schema 深相等+additionalProperties is False；handler handle({}, HandlerContext(cast(Kernel,None),"demo.ping"))=="pong"+command_id；isinstance CommandHandler 协议；commands() 恰一元素+is 断言；provider 八字段逐字+_writer 可调；formats() 恰一元素 is 断言；dataclasses.fields 八字段名集合+can_read bool+target∈{"shape","xcaf"}。
- `tests/plugins/test_demo_installed.py`（6 例，**全仓唯一真安装测试** #round9-6/#round11-NB6）— 全部断言在子进程 `[sys.executable,"-c",code]`（cwd=仓库根、env 继承、主进程禁 import demo）。fixture 链：session 级 `ensure_pip`（`-m ensurepip --upgrade` returncode≠0→fail）→ class 级 `demo_installed`（`-m pip install -e <repo>/plugins_examples/mycad_plugin_demo --no-build-isolation --quiet` returncode≠0→fail【安装失败=测试失败】→ yield → teardown `-m pip uninstall -y mycad-plugin-demo --quiet` + 残留断言子进程 `find_spec('mycad_plugin_demo') is None` returncode≠0→fail【卸载残留=测试失败】）。例：①`registry.search("demo.ping")==["demo.ping"]`+`list_by_category()` 全展 9 id（8 内置+demo.ping，BUILTIN_IDS 经主进程 import mycad.builtin_commands 取）；②`new_document(s).bus.execute("demo.ping",{})=="pong"`（handler_factory 生效）；③`formats.resolve(x.txt)` isinstance FormatPort+name=="TXT-SUMMARY"+`.write(kernel,path)` 实写文件（先 feature.box 2×3×4）内容含 "solids=1"+"volume"；④两次 build_app 快照（commands/providers/distributions）equal 且 ==["demo.ping"]/["TXT-SUMMARY"]/["mycad-plugin-demo"]；⑥PluginManager 可见 manifest 五字段（id/version/api_version/permissions=[]/homepage=""+warnings=[[]]）；⑤`TestAfterUninstall` 类置文件最后（class fixture teardown 后运行）——search/contributions/providers 全空+残留探针 0。
- `README.md` — 文末追加「## 插件与安全」段：同进程加载=完全信任作者（无沙箱/签名/权限强制，ADR-003）、permissions 阶段 0 仅声明、装前审源码、demo 见 plugins_examples/。

### 四门（scoped，T9c 实测）

1. `-m pytest tests/plugins/ tests/app/ -q` → **133 passed in 54.24s**（demo 净增 15：module 9+installed 6；installed 单文件 6 passed in 43.33s，含 ensurepip+editable 安装+卸载+残留链路；app 无回归）。
2. `-m basedpyright plugins_examples/ tests/plugins/test_demo_module.py tests/plugins/test_demo_installed.py` → **0/0/0**（demo 源码同样过 strict）。
3. `-m ruff check plugins_examples/ tests/plugins/ README.md` → All checks passed。
4. `-m ruff format --check plugins_examples/ tests/plugins/` → 11 files already formatted。
- **篡改探针**：demo handler 返回值 "pong"→"pang" → installed 例② **1 failed**；还原 → 该例+module 全部 **10 passed**（红→绿闭环）。

### Deviations / 设计说明

- **D9（installed 例⑥补 manifest 可见性例）**：任务书「⑥安装阶段失败即 fail（fixture 内断言）」系 fixture 行为而非独立测试函数，为达 ≥6 例补「manifest 经 PluginManager 五字段可见」例（QA 与 T10 plugins 子命令的数据面）。
- **D10（json 载荷窄化用 cast 而非 isinstance）**：basedpyright strict 下 `isinstance(x, list)` 把 object 窄化为 `list[Unknown]`，后续 `len()`/索引触发 reportUnknownArgumentType/VariableType（4 errors 实测）；改 `cast("list[str]", ...)`/`cast("dict[str, object]", ...)` 精确窄化（仓库既定 cast 模式，非 ignore）。

### QA 终稿（T9，实测数据逐字）

- **① happy（editable 安装 demo→build_app→execute→发现列表等价输出）**：`pip install -e plugins_examples/mycad_plugin_demo --no-build-isolation --quiet` 耗时 **2.35s**；子进程输出逐字：
  ```
  {"execute_result": "pong", "plugins_list": ["mycad-plugin-demo mycad-plugin-demo 0.1.0 commands=[demo.ping] formats=[TXT-SUMMARY] warnings=[]"]}
  ```
- **② failure（进程内 monkeypatch fake EP：future+bad 夹具）**：`mycad_plugin_future`（api 9.9）+`mycad_plugin_bad.missing_attr`（无 manifest）两 EP 喂真 EntryPointDiscoverer，输出逐字：
  ```
  builtins: 8 ['feature.box', 'feature.cylinder', 'feature.extrude', 'feature.hole', 'feature.hole_pattern', 'feature.revolve', 'modify.boolean_cut', 'modify.fillet']
  skipped: [('mycad_plugin_bad.missing_attr', 'missing-manifest'), ('mycad_plugin_future', 'incompatible-api')]
  warnings_total: 2
  builtin_executable: True
  ```
  （核心 8 命令仍全在册且 feature.box 经 bus 可执行；warnings==2；skip id 与 reason 正确。）
- **③ 卸载后恢复空**：`pip uninstall -y mycad-plugin-demo --quiet` 后子进程输出逐字：
  ```
  {"demo_hits": [], "contributions": [], "providers": [], "builtin_count": 8}
  RESIDUAL: none
  ```
