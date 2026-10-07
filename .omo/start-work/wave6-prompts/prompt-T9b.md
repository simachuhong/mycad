# T9b 任务书：插件装载器 + app.py 真接线（冲突隔离/兑底/信号钩）

你是 MyCAD 项目 T9b 片的执行代理。**第一动作：`cat` 本文件已完成。按 §5 清单机械执行，禁重新设计。**

## 0. 反停摆五纪律（违反=任务失败）

1. 禁写清单外文件；2. 单文件一次写 ≤100 行（cat > / cat >>）；3. 每回合一个小动作；4. 禁长推理——设计已钉死；5. 遇阻输出 `BLOCKED: <原因>` 结束回合。

## 1. 白名单（仅允许创建/修改）

- 新建 `src/mycad/plugins/loader.py`
- 修改 `src/mycad/app.py`（仅两处接线：line 59 `del discoverers` 替换 + handler 装配抽取 `_handler_map` 含 None 兑底；禁动其余逻辑）
- 新建 `tests/plugins/test_loader.py`
- 追加 `.omo/evidence/task-9-phase0-mvp.md` §T9b
- **禁改**：types.py/manager.py/manifest.py/discovery.py/commands//core//formats//geom//tests/fixtures/plugins/；禁 git；禁 pip。

## 2. 上下文（勿重复勘察）

- 计划原文：`sed -n '400,428p' .omo/plans/phase0-mvp.md`（B0 必读，loader/信号钩/冲突语义段）。
- **T9a 已交付**：`mycad.plugins.discovery.EntryPointDiscoverer`（构造 groups 默认两组）；`mycad.plugins.manifest.resolve_manifest`；`plugins/__init__` 已导出七名；tests/fixtures/plugins/ 七棵夹具树（conftest 已注入 sys.path——test_loader.py 可直接用）。夹具 `mycad_plugin_conflict`（feature.box 冲突命令 + .txt priority=100 provider）为本片核心夹具。
- **app.py 现状**（92L）：line 59 `del discoverers  # T9 wires real discoverers`；line 86-88 插件贡献循环仅 factory 非 None 时注册 handler。`cat src/mycad/app.py` 精读后再动。
- registry.register(spec) 同 (id,version)→CommandConflictError(message, command_id)；FormatProviderRegistry.register 同优先级扩展名重叠→ProviderConflictError(extension, provider1, provider2)（formats/registry.py）。
- CommandContribution(spec, handler_factory|None)；BuiltinModelingHandler(command_id)（core/handlers.py）。
- 六码经 get_args(WARNING_REASON) 派生（T7b manager.py `_MISSING_MANIFEST` 模式；command-conflict/provider-conflict/load-error 对应 get_args 索引 3/4/5）。

## 3. 钉死设计

### 3.1 `src/mycad/plugins/loader.py`

- `def register_plugins(registry: CommandRegistry, formats_registry: FormatProviderRegistry, discovered: Sequence[DiscoveredPlugin]) -> tuple[DiscoveredPlugin, ...]`：
  1. 逐插件（入参序，discovery 已排好）：
  2. **命令**：逐条 `registry.register(c.spec)`；CommandConflictError→**跳过该条目**（不跳整插件其余命令）+收集 warning（command-conflict 码）。
  3. **格式**：逐条 `formats_registry.register(p)`；ProviderConflictError→**跳过该 provider 条目**（不跳整插件）+warning（provider-conflict 码）。
  4. 每插件用 `dataclasses.replace(dp, commands=<存活 tuple>, formats=<存活 tuple>, warnings=<原+新码去重保序>)` 生成新 DiscoveredPlugin。
  5. 返回新 tuple（交 PluginManager 构造）。
- docstring 注明：warnings 只携六码；name/vendor 细节经 ProviderConflictError 字段断言于直注册单元测试（规格「warning 含两 provider name/vendor」以此满足——evidence 记解释）。
- `__all__ = ["register_plugins"]`。

### 3.2 app.py 两处接线

- **替换 line 59**：`del discoverers` → `discoverers = tuple(discoverers) if discoverers is not None else (EntryPointDiscoverer(),)`（None→默认真发现；显式 []→空发现保持）；顶部 import `from mycad.plugins.discovery import EntryPointDiscoverer` + `from mycad.plugins.loader import register_plugins`。
- 装配流：`discovered = tuple(d.discover() for d in discoverers)`（多 discoverer 串联）→ `loaded = register_plugins(registry, formats, discovered)` → `plugins = PluginManager(loaded)`。
- **handler 装配抽取**：模块级 `def _handler_map(registry: CommandRegistry, plugins: PluginManager) -> dict[str, CommandHandler]:`——内置 {spec.id: BuiltinModelingHandler(spec.id) for spec in registry 全部}（保持现有 8 命令装配语义）+ 插件贡献：factory 非 None→factory()；**factory None→BuiltinModelingHandler(contribution.spec.id) 兑底**（新 else 分支）。new_document 改调 `_handler_map(services.registry, services.plugins)`（每次 new_document 现装配，语义不变）。
- app.py 其余（AppServices/build_app 骨架/FormatProviderRegistry/PluginManager(()) 初始）不动；AppServices 字段不变。

### 3.3 `tests/plugins/test_loader.py`（≥13 例）

进程内，禁 pip。夹具：FakeSpec 构造 helper（自造 CommandSpec）+ FakeProvider（.t9b 扩展名八字段）+ 经 conftest 用 mycad_plugin_conflict。

1. **冲突命令跳过**：registry 预注册 feature.box（真 builtin spec 或等价自造）→register_plugins 装载 conflict 插件→返回 tuple 中该插件 commands 不含 feature.box 条目+warnings 含 command-conflict 码；registry.get("feature.box") 仍返回内置版本。
2. **provider 冲突跳过条目**：formats_registry 预注册 .txt priority=100 伪 provider→装载 conflict→formats 空+provider-conflict 码；**直注册断言**：再次 register 同 priority 同扩展名→pytest.raises(ProviderConflictError) 断言 extension==".txt"+provider1/provider2 各含 name/vendor 元组。
3. **不跳整插件**：插件两条命令一条冲突一条不冲突→不冲突条存活+注册成功。
4. **无冲突零 warning**：正常装载 warnings==()。
5. **warnings 去重保序**：同插件两条命令同 id 冲突→一条 warning。
6. **返回可交 PluginManager**：PluginManager(register_plugins(...)) 构造成功+loaded() 含正常插件。
7. **_handler_map 兑底**：registry 注册自造 spec（demo.fallback）+PluginManager 持 CommandContribution(spec, handler_factory=None)→_handler_map 返回 dict["demo.fallback"] isinstance BuiltinModelingHandler。
8. **_handler_map factory 优先**：contribution factory=零参 lambda 返 FakeHandler→dict 值是该 handler 实例（is 断言）。
9. **_handler_map 内置全量**：真 builtin_commands 8 spec 注册后 _handler_map 恰含 8 键（值全 BuiltinModelingHandler）。
10. **build_app None→真发现**：monkeypatch EntryPointDiscoverer.discover 返 ()→build_app(None) 成功 8 命令（等价空环境）；**显式 []→不调 discoverer**（monkeypatch 计数为 0）。
11. **多 discoverer 串联**：两个 fake discoverer 各返一插件→PluginManager 持两者。
12. **register_plugins 纯函数性**：入参 discovered tuple 不被修改（返回新对象）。
13. **信号钩异常隔离**（规格集成）：真 Document+CommandBus 装配（app.build_app([]) 或手工），bus.execute 前经 document.events.subscribe("pre_command", 抛异常回调)+正常计数回调→execute 正常完成+异常被 RuntimeWarning 隔离（SignalBus 语义已有测试，此处集成层面断言命令成功+另一回调收到）。

## 4. 通用纪律

同 T9a：SPDX 两行头/basedpyright strict 零 ignore/ruff 全过/测试 docstring 禁守卫字面量/禁 git。

## 5. 执行清单

- B0：sed 取计划 400-428；`cat src/mycad/app.py src/mycad/formats/registry.py src/mycad/commands/registry.py`；`cat tests/plugins/conftest.py` + 夹具 conflict 树。
- B1：写 loader.py（一块）。
- B2：写 test_loader.py 首块（例 1-6）+跑红。
- B3：修 loader.py 至例 1-6 绿。
- B4：追加例 7-9（_handler_map）；app.py 抽取改造；跑绿。
- B5：追加例 10-12（build_app 接线）；app.py line 59 替换；跑绿。
- B6：追加例 13（信号钩集成）；跑绿。
- B7：scoped 四门：`.venv/bin/python -m pytest tests/plugins/ tests/app/ tests/builtin_commands/ -q`（app.py 改动波及）+ `.venv/bin/basedpyright src/mycad/plugins/loader.py src/mycad/app.py tests/plugins/test_loader.py` + `.venv/bin/ruff check src/mycad/plugins/ src/mycad/app.py tests/plugins/` + `format --check` 同路径。
- B8：追加 evidence §T9b（交付物/四门/warnings 携码解释性偏离/_handler_map 抽取说明）。
- B9：输出 DoneClaim JSON（同 T9a 格式，task 字段 "T9b"）。
