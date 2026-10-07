# Task 7 — phase-0 evidence

## §T7a builtin_commands 包

- 执行者：T7a（`.omo/start-work/wave5-prompts/prompt-T7a.md`，逐字执行）
- 日期：2026-10-06

### 交付物

- `src/mycad/builtin_commands/__init__.py` — 再导出 `COMMAND_SCHEMA_DEFS` / `BUILTIN_COMMAND_SPECS` / `BUILTIN_COMMAND_IDS`（A.1 目录序，`tuple(spec.id for spec in BUILTIN_COMMAND_SPECS)`）。
- `src/mycad/builtin_commands/defs.py` — 附录 A.0 的单一正式转录：`COMMAND_SCHEMA_DEFS: Mapping[str, Any]`，键恰 11 个（FaceSelector/EdgeSelector/Position/Depth/Pattern/Profile/Mode/Center3/Positive/Tool/Hole）；内部共享一律 `{"$ref": "#/$defs/<Name>"}`，无复制子结构。
- `src/mycad/builtin_commands/specs.py` — 8 条 `CommandSpec`（A.1 目录序），全部 version=1、`undo_compensation="history_replay"`；`feature.hole` 为根级 `{"$ref": "#/$defs/Hole"}`（#round11-3）；`modify.boolean_cut` 不含 mode 键，`cut` 唯一映射之。
- `tests/builtin_commands/__init__.py`、`tests/builtin_commands/test_defs.py`（15 tests：11 def 双重独立转录 + $ref 形态 + 禁复制守卫）、`tests/builtin_commands/test_specs.py`（33 tests：8 spec 逐字段 + 注册表 + validate_params 冒烟 ×5 + P1/P2 泄漏 + AFFECTED_OBJECTS + PlannedCommand 表外 + AST 单一赋值 + CLI 别名唯一）。
- 本文件 §T7a。

### 四门（scoped，全部 `.venv/bin/python`）

1. `-m pytest tests/builtin_commands/ -q` → **48 passed**。
2. `-m basedpyright src/mycad/builtin_commands/ tests/builtin_commands/` → **0 errors, 0 warnings, 0 notes**。
3. `-m ruff check src/mycad/builtin_commands/ tests/builtin_commands/` → **All checks passed**。
4. `-m ruff format --check ...` → **6 files already formatted**（gate 前先 format 1 文件后复跑 check 与 pytest，仍全绿）。

附加差异化增量：`pytest tests/test_spdx.py tests/test_layering.py tests/test_core_isolation.py -q` → 6 passed（新文件未破坏全树元测试）。

红→绿闭环：A3 `test_defs` 红（`ModuleNotFoundError: mycad.builtin_commands.defs`）→ A7 绿（15 passed）；A10 `test_specs` 红（`ImportError: cannot import name 'BUILTIN_COMMAND_IDS'`）→ A12 绿（48 passed）。

### A0 勘察结论

`src/mycad/commands/validation.py` 的 `_ALLOWED_KEYWORDS`（20 关键字固定子集）**明确包含** `description`（doc-only）、`const`（`==` 主动校验）、`default`（仅填缺失键、绝不覆盖显式值）→ 附录 A.0/A.1 的 `description` / `const` / `default` **逐字保留**，无需剥离或改写（revolve 的 axis 保留 `{"const":"X"}` / `{"const":"Y"}` 形态）。

对附录 A.0 JSON 的机器校验（`json.loads` 计划原文 vs `COMMAND_SCHEMA_DEFS`）：11/11 键一致；除 Profile（D2）外 10 个 def **逐字节相等**（含全部中文 description 与默认值）。

### Deviations

- **D1（SPDX 头）**：任务书字面为 MIT + "MyCAD Contributors"，但 `tests/test_spdx.py` 对 src/tests/scripts 全树 `.py` 强制 `# SPDX-FileCopyrightText: 2026 MyCAD contributors` + `# SPDX-License-Identifier: Apache-2.0`（且 LICENSE/pyproject 均 Apache-2.0；任务书自身亦要求"参照 src/mycad/core/exceptions.py 现有文件头格式"）→ 采用仓库强制格式。
- **D2（Profile 正数参数与 exclusiveMinimum 计数）**：任务书钉死 Profile 的 radius/width/height 用 `Positive`（$ref），A.0 原文为内联 `{"type":"number","exclusiveMinimum":0.0}` → 按钉死采用 `$ref`（语义等价）；Pattern.radius 按钉死与 A.0 保持内联 → defs.py 源文本 `"exclusiveMinimum": 0.0` 出现 **3** 次（Positive / Depth.blind.value / Pattern.radius）而非任务书预告的 2，守卫断言依任务书"按实际调整断言并记 deviation"条款调整为 3。
- **D3（tests/__init__ "空文件"）**：实现为 SPDX 头 + 一行 docstring（与 `tests/commands` 等现有包标记一致）；字面空文件违反 `test_spdx.py` 的两行头强制。

### Notes

- PlannedCommand 表外 id（feature.sweep / modify.chamfer / datum.xy / "" / feature.boxx）实际抛 `UnknownCommandError`（`document.py` 的 `__post_init__` 门，非 ValidationError）——任务书已预留"或规格实际异常类型"选项，A0 已 cat document.py 确认。
- AST 单一赋值守卫同时检查 `ast.Assign` 与 `ast.AnnAssign`（钉死的注解形式 `COMMAND_SCHEMA_DEFS: Mapping[str, Any] = ...` 解析为 AnnAssign）；全 src/mycad 命中恰 `src/mycad/builtin_commands/defs.py` 一处。
- 注册表 id 枚举经 `list_by_category()`（CommandRegistry 无 `__iter__`，任务书允许"或等价 API"）。
- 全部 8 个根 schema 均带 `additionalProperties: false`（A.2 全局约定；任务书钉死仅对 box/hole_pattern/boolean_cut 显式列出，fillet 拒绝多余键的 QA 场景要求之，与 `tests/commands/_fixtures.py` 测试侧先例一致）。
- 白名单遵守：commands/、core/、plugins/、agent/、app.py、tests/commands/ 等零改动（T7b/T7c 范围未触碰）；无 git 操作。

## §T7b 插件契约 types/manager + agent 占位

- 执行者：T7b（`.omo/start-work/wave5-prompts/prompt-T7b.md`，逐字执行）
- 日期：2026-10-06

### 交付物

- `src/mycad/plugins/types.py` — 跨波公开契约唯一定义处（#round9-4）：`CURRENT_API_VERSION="1.0"`、`CURRENT_API_MAJOR=1`、`WARNING_REASON`（六码 Literal）+ `WARNING_REASONS`（等值 frozenset）、`CommandContribution(spec, handler_factory)`（frozen，恰两字段）、`PluginDiscoverer`（runtime_checkable Protocol，仅 `discover()`）、`DiscoveredPlugin`（frozen，恰六字段，顺序写死）、`PluginManifest`（frozen，恰五字段）。零发现逻辑（定位算法归 T9）。
- `src/mycad/plugins/manager.py` — `PluginManager`（frozen，自定义 `__init__(discovered: Sequence[DiscoveredPlugin] = ())` 经 `object.__setattr__` 存 `discovered_plugins: tuple`；构造形态 `PluginManager(())` / `PluginManager()` / `PluginManager(discovered=[...])` 均支持）+ `loaded()` / `skipped()` / `command_contributions()` / `format_providers()` 四视图。
- `src/mycad/plugins/__init__.py` — 再导出恰六名（PluginDiscoverer/DiscoveredPlugin/CommandContribution/PluginManifest/PluginManager/CURRENT_API_VERSION）+ `__all__`。
- `src/mycad/agent/plan_types.py` — 协议占位：阶段 0 仅类型再导出 `Plan`/`PlannedCommand`/`InvalidPlanTransition`（B0 勘察：状态转移全为 Plan 方法、无纯函数，故按任务书"只再导出两类与异常类"）。
- `src/mycad/agent/__init__.py` — 同三名再导出；零网络/零 LLM/无 schema_catalog/无工具 schema 生成。
- `tests/plugins/__init__.py`（SPDX 标记）、`tests/plugins/test_types.py`（11 tests：三 dataclass 字段名逐字锁 + WARNING_REASON 六码集合锁 + API 常量 + CommandContribution 双形态构造与 frozen + Protocol 结构探测正反例 + AST 单一定义守卫 + AST reason 字面量守卫）、`tests/plugins/test_manager.py`（4 tests：空构造双形态 + list→tuple + 混合三插件夹具 + frozen）、`tests/plugins/test_agent.py`（3 tests：agent 公开面 + 零网络扫描 + plugins 公开面六名）。
- 本文件 §T7b。

### 四门（scoped，全部 `.venv/bin/python`）

1. `-m pytest tests/plugins/ -q` → **18 passed**。
2. `-m basedpyright src/mycad/plugins/ src/mycad/agent/ tests/plugins/` → **0 errors, 0 warnings, 0 notes**。
3. `-m ruff check src/mycad/plugins/ src/mycad/agent/ tests/plugins/` → **All checks passed**。
4. `-m ruff format --check src/mycad/plugins/ src/mycad/agent/ tests/plugins/` → **9 files already formatted**（零改写，手写即合规）。

红→绿闭环：B2 `test_types.py` 红（`ModuleNotFoundError: No module named 'mycad.plugins'`）→ B4 types.py 落盘后 11 passed。

### skipped 语义薄实现说明

- `loaded()`：manifest 非 None 即算 loaded（任务书明示薄实现；T9 接真发现后细化为"且无整体跳过码"）。
- `skipped()`：manifest None **或** warnings 非空者入选；reason 取 warnings 首个码，manifest None 且无 warnings 时取 missing-manifest 码。薄实现下"manifest 非 None 但带 warnings"的插件会同时出现在 loaded() 与 skipped()——T9 以真实跳过码消歧。
- missing-manifest 码不写字面量：AST reason 字面量守卫（#round9-5）要求六码字面量仅存于 types.py，故 manager.py 以 `get_args(WARNING_REASON)[0]` 派生（types.py Literal 源序首位即该码，T9 禁改 types.py 故源序稳定）。

### Deviations

- **D1（tests/plugins/__init__.py "空"）**：实现为 SPDX 头 + 一行 docstring（与 §T7a D3 同因：`test_spdx.py` 全树两行头强制）。
- **D2（dir() 公开面断言含子模块名）**：`from mycad.plugins.types import ...` / `from mycad.agent.plan_types import ...` 会使导入系统给包挂 `types`/`manager`/`plan_types` 子模块属性（dir() 可见、非下划线）。test_agent.py 以显式 `SUBMODULE_ARTIFACTS` 集合排除后断言相等（agent 侧任务书 ⊆ 语义收紧为 ==，同时锁定缺失与多余）。
- **D3（frozen 断言形态）**：沿用仓库先例 `obj.__setattr__("field", v)`（tests/commands/test_spec.py）而非直接属性赋值——直赋会触发 basedpyright 诊断且本项目零 ignore 政策不允许 `type: ignore`。

### Notes

- B0 勘察：`mycad.core.plan` 的状态转移（confirm/mark_executing/mark_done/mark_failed/cancel）全部是 Plan 方法，`_LEGAL` 表与 `InvalidPlanTransition` 为模块内部/异常类 → agent 仅再导出 Plan/PlannedCommand/InvalidPlanTransition。
- `PlannedCommand` 实际定义于 `mycad.core.document`，`core.plan` 有再导入，按任务书钉死形态 `from mycad.core.plan import Plan, PlannedCommand` 取用。
- test_manager 夹具 A 的 FormatProvider 用 T8 真实例 `STEP_PROVIDER`（`mycad.formats.providers`）。
- frozen dataclass 含 callable 字段时相等性按函数身份比较：测试中同一 DiscoveredPlugin 实例复用比较（勿两次 `_plugin_a()` 构造后断言相等，lambda 工厂不等）。
- 白名单遵守：仅创建/修改本片清单内 10 文件；builtin_commands/、commands/、core/、formats/、geom/、app.py 零改动；无 git 操作。

## §T7c 组合根 + 集成

- 执行者：T7c（`.omo/start-work/wave5-prompts/prompt-T7c.md`）前半；实例 ses_eee12b653ffe9gjsKnu16pIoGU 于 10-07 00:02:31 死于配额墙（app.py+test_composition+test_builtin_execution 前六命令+test_layering 白名单已落盘），C8 fillet/cut 两节+flange QA+evidence+终验由编排方接管完成（先例 T8b/D11）。

### 交付物

- `src/mycad/app.py`（92L）— AppServices frozen 恰四字段（registry/kernel/formats/plugins）；`build_app(discoverers=None)`：CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)+BUILTIN_COMMAND_SPECS 显式逐个注册+BuildKernel()+FormatProviderRegistry([STEP_PROVIDER,STL_PROVIDER])+PluginManager(())；`new_document(services,*,confirmed_by=None)`：8×BuiltinModelingHandler 装配+Document+CommandBus，返回前恰一次 kernel.reset()。
- `tests/test_layering.py` — app.py 单列白名单（唯一允许同时 import geom+core 的 src 模块；仍禁 build123d/OCP/numpy）。
- `tests/app/test_composition.py`（85L）— 8 id 排序逐字+fields 锁定+metadata 初值+跨文档隔离（doc1 box solid_count=1→new_document→doc2 solid_count=0 volume=0.0）+feature.sweep→UnknownCommandError。
- `tests/app/test_builtin_execution.py`（211L+接管追加）— 8 命令三件套：合法执行（含体积公式断言）/校验失败/grammar 往返 parse_line(to_cli(id,params,registry))==(id,default-填充 params)；modify.fillet 残留 pattern:{kind:linear} 键→ValidationError。
- `tests/app/test_flange_qa.py`（接管新建）— golden 法兰 8 命令最小序列（模式 A）。

### 四门（scoped）

1. `-m pytest tests/app/ tests/test_layering.py tests/builtin_commands/ tests/plugins/ -q` → **102 passed**。
2. `-m basedpyright src/mycad/app.py tests/app/ tests/test_layering.py` → **0/0/0**。
3. `-m ruff check src/mycad/app.py tests/app/` → All checks passed。
4. `-m ruff format --check` → 5 files already formatted。

### mode=new 勘察结论（C0）

`_b123_ops._combine`：new=替换整体（fresh solid）、add=fuse、cut=subtract → flange QA 采用**模式 A**（cylinder mode=new 替换前序毛坯；fillet/cut 后 undo(2) 回到法兰净坯）。

### Golden 法兰 QA 实测（模式 A 序列）

box(10³)→extrude(circle r5 d10)→revolve(rect w2 h5 center[0,10] axis X)→cylinder(r40 h8 mode=new)→fillet(r1)→boolean_cut(box 工具)→undo(2)→hole(d20 through_all)→hole_pattern(base d6 polar r25 count4)：

- 终态 volume = **36794.33315884364**（解析期望 π·8·(1600−100−36)=36794.333158843656，delta≈1.6e-11 < 1e-6）
- solid_count = **1**；历史 ids = **[box, extrude, revolve, cylinder, hole, hole_pattern]**（undo(2) 移除 fillet/cut）

8 id 排序列表：feature.box / feature.cylinder / feature.extrude / feature.hole / feature.hole_pattern / feature.revolve / modify.boolean_cut / modify.fillet

Help 文本（f"{spec.id}: {spec.summary_en}"）：

```
feature.box: Create a rectangular box
feature.cylinder: Create a cylinder
feature.extrude: Extrude a parametric profile
feature.hole: Drill a predicate-located hole
feature.hole_pattern: Pattern a predicate-located hole
feature.revolve: Revolve a parametric profile
modify.boolean_cut: Subtract an inline tool solid
modify.fillet: Fillet selected edges
```

### Deviations

- **D1（revolve 合法执行形态，接管修复）**：子代理首版 rect center [10.0,0.0] 绕 X 轴——矩形跨旋转轴（y∈[-2.5,2.5] 过 y=0）→ OCC BRep_API 拒绝。修为 center [0.0,10.0] 离轴（T2 tests/geom/test_features.py 先例），断言改解析体积 2π·10·(2·5)。
- **D2（flange QA 模式选型）**：模式 A（mode=new 替换+undo 复原）替代模式 B；依据 _combine 语义勘察，evidence 记录在案。
- **D3（format 两处）**：接管前 test_builtin_execution/test_composition 各 1 文件 ruff format 未过，format 后并入。
- **D4（DoneClaim）**：接管模式无子代理 DoneClaim，以本节+编排方复跑四门为采信记录（先例 T8b §D）。
