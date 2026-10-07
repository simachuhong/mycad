# T7b：插件契约 types/manager + agent 占位（锁定测试）

你是 MyCAD phase-0 计划的 T7b 执行者。本提示词是唯一任务书，逐字执行。
计划 `.omo/plans/phase0-mvp.md` 行 350-379（T7 段，plugins/types 与 agent 小节）为权威规格。
**第一动作：`cat` 本文件已完成；随后 B0 逐项读取参考源码，禁止跳过。**

## 反停摆五纪律（每回合必须遵守）
1. 禁写清单文件/计划文件；执行清单只在脑内。
2. 单次写文件 ≤100 行（大文件 `cat >` 首批 + `cat >>` 追加）。
3. 每回合只做一个小动作。
4. 禁长推理：设计已钉死在本文，照抄执行；遇规格冲突记 deviation 后选本文规则。
5. BLOCKED 立即停并输出原因。

## 白名单（仅允许创建/修改以下文件）
- `src/mycad/plugins/__init__.py`（新建）
- `src/mycad/plugins/types.py`（新建）
- `src/mycad/plugins/manager.py`（新建）
- `src/mycad/agent/__init__.py`（新建）
- `src/mycad/agent/plan_types.py`（新建）
- `tests/plugins/__init__.py`（新建，空）
- `tests/plugins/test_types.py`（新建）
- `tests/plugins/test_manager.py`（新建）
- `tests/plugins/test_agent.py`（新建）
- `.omo/evidence/task-7-phase0-mvp.md`（追加 `## §T7b` 段；T7a 已建文件，只追加不改动已有内容）

**禁改**：src 与 tests 其余一切（含 builtin_commands/、commands/、core/、formats/、geom/、app.py）；禁 git 操作。

## 通用规则
- SPDX 两行头（参照 src/mycad/core/exceptions.py）。
- basedpyright strict 零 ignore；ruff 零豁免。
- types.py 是跨波公开契约：**T9 只 import 消费，禁在此文件增删改字段——所以本片必须一次写对**。

## B0 前置读（依次，禁止跳过）
1. `cat src/mycad/commands/spec.py`（CommandSpec/CliSyntax 签名——CommandContribution.spec 类型来源）。
2. `cat src/mycad/core/handlers.py`（CommandHandler Protocol——handler_factory 返回类型来源）。
3. `cat src/mycad/formats/base.py`（FormatProvider——DiscoveredPlugin.formats 类型来源）。
4. `cat src/mycad/core/plan.py`（Plan/PlannedCommand/状态转移函数名——agent/plan_types 再导出源）。
5. `sed -n '350,379p' .omo/plans/phase0-mvp.md`（T7 段 plugins/types 与 agent 小节原文）。
6. `cat tests/builtin_commands/test_specs.py`（T7a 测试风格参照；若不存在说明 T7a 未交付，BLOCKED）。

## 钉死设计（照抄，勿发明）

### plugins/types.py（全部公开契约唯一定义处）
imports：`from collections.abc import Callable`、`from dataclasses import dataclass`、`from typing import Literal, Protocol, runtime_checkable`、`from mycad.commands.spec import CommandSpec`、`from mycad.core.handlers import CommandHandler`、`from mycad.formats.base import FormatProvider`、`from typing import Sequence`（或 collections.abc，按 ruff 习惯）。

模块常量：`CURRENT_API_VERSION: str = "1.0"`、`CURRENT_API_MAJOR: int = 1`；
`WARNING_REASON = Literal["missing-manifest","manifest-error","incompatible-api","command-conflict","provider-conflict","load-error"]`；
`WARNING_REASONS: frozenset[str] = frozenset(get_args(WARNING_REASON))`（import get_args from typing）。

1. `@dataclass(frozen=True) class CommandContribution:` 字段恰两个：`spec: CommandSpec`、`handler_factory: Callable[[], CommandHandler] | None`。
2. `@runtime_checkable class PluginDiscoverer(Protocol):` 仅一方法 `def discover(self) -> Sequence[DiscoveredPlugin]: ...`（注意前向引用：文件内 DiscoveredPlugin 定义在后，用 `from __future__ import annotations` 或字符串注解解决）。
3. `@dataclass(frozen=True) class DiscoveredPlugin:` 字段**恰六个**（顺序写死）：`distribution_name: str`、`entrypoint: tuple[str, ...]`、`manifest: PluginManifest | None`、`commands: tuple[CommandContribution, ...] = ()`、`formats: tuple[FormatProvider, ...] = ()`、`warnings: tuple[str, ...] = ()`。
4. `@dataclass(frozen=True) class PluginManifest:` 字段恰五个：`id: str`、`version: str`、`api_version: str`、`permissions: tuple[str, ...] = ()`、`homepage: str = ""`。
（manifest 定位算法/EntryPointDiscoverer 是 T9 实现，本片不写任何发现逻辑。）

### plugins/manager.py
`from mycad.plugins.types import CommandContribution, DiscoveredPlugin, FormatProvider`；
`@dataclass(frozen=True) class PluginManager:` 字段一个：`discovered_plugins: tuple[DiscoveredPlugin, ...] = ()`（构造签名 `def __init__(self, discovered: Sequence[DiscoveredPlugin] = ())` 经自定义 __init__ 转 tuple 存 discovered_plugins，或直接 dataclass 字段+默认——**构造调用形态必须支持 `PluginManager(())` 与 `PluginManager(discovered=[...])`**；选自定义 __init__ 包装最稳）。
方法：`loaded() -> tuple[DiscoveredPlugin, ...]`（manifest 非 None 且 warnings 中无整体跳过码者——薄实现：manifest 非 None 即算 loaded）、`skipped() -> tuple[tuple[str, str], ...]`（(distribution_name, reason) 对，manifest 为 None 或 warnings 非空者取其 warnings 首个码；manifest None 且无 warnings → "missing-manifest"）、`command_contributions() -> tuple[CommandContribution, ...]`（遍历 loaded 拼接 commands）、`format_providers() -> tuple[FormatProvider, ...]`（遍历 loaded 拼接 formats）。
skipped 语义薄实现允许（T9 会接真发现结果），evidence 记录实现选择。

### plugins/__init__.py
再导出恰六名：`PluginDiscoverer, DiscoveredPlugin, CommandContribution, PluginManifest, PluginManager, CURRENT_API_VERSION`（`from mycad.plugins.types import ...` + `from mycad.plugins.manager import PluginManager`）。

### agent/plan_types.py
`from mycad.core.plan import Plan, PlannedCommand` + core.plan 内状态转移纯函数（B0 第 4 项勘察实际函数名，如 InvalidPlanTransition 相关或 mark_* 方法若全是方法则只再导出两类与异常类）；docstring 注明「协议占位：阶段 0 仅类型再导出」。
### agent/__init__.py
`from mycad.agent.plan_types import Plan, PlannedCommand`（+勘察到的导出）；**零网络/零 LLM/无 schema_catalog/无工具 schema 生成代码**。

### test_types.py（契约锁定）
- `dataclasses.fields` 断言：DiscoveredPlugin 字段名元组逐字 == ("distribution_name","entrypoint","manifest","commands","formats","warnings")；PluginManifest == ("id","version","api_version","permissions","homepage")；CommandContribution == ("spec","handler_factory")。
- WARNING_REASON 锁定：`get_args(WARNING_REASON)` 逐字等于六值元组（顺序无关但集合+长度相等）；`WARNING_REASONS == frozenset(get_args(WARNING_REASON))`；CURRENT_API_VERSION=="1.0"、CURRENT_API_MAJOR==1。
- CommandContribution 双形态构造（#round9-4 验收）：①用 T3 真实 CommandSpec（`from mycad.builtin_commands import BUILTIN_COMMAND_SPECS; spec = BUILTIN_COMMAND_SPECS[0]`）+ handler_factory=None；②零参工厂 `lambda: BuiltinModelingHandler("feature.box")`（from mycad.core.handlers import BuiltinModelingHandler）。两种均构造成功且 frozen（改属性 → FrozenInstanceError）。
- PluginDiscoverer Protocol：`isinstance` 结构探测（runtime_checkable）——定义一个带 discover 的最小类通过、缺 discover 的类不通过。
- **AST 唯一定义守卫**：walk `src/mycad/**/*.py`，ast.parse 找 ClassDef 且 name=="CommandContribution"，断言命中文件恰为 ["src/mycad/plugins/types.py"]。
- **AST reason 字面量守卫**（#round9-5，T9 后仍须绿）：walk `src/mycad/**/*.py` 收集所有字符串常量，凡命中 {"missing-manifest","manifest-error","incompatible-api","command-conflict","provider-conflict","load-error"} 之一者，断言其所在文件 ∈ {src/mycad/plugins/types.py}（types.py 的 WARNING_REASON Literal 定义本身允许）。（docstring 纪律：本测试文件 docstring 禁写这六个字面量。）

### test_manager.py
- 空构造：PluginManager(()) 与 PluginManager()；loaded()==()、skipped()==()、command_contributions()==()、format_providers()==()。
- 混合三插件夹具（手写 DiscoveredPlugin：A=带 manifest 且零 warnings+1 command 贡献；B=manifest None+warnings=("incompatible-api",)；C=带 manifest 但 commands 空）：loaded() 含 A、C 不含 B；skipped()==(("B-dist","incompatible-api"),)（分布名自定）；command_contributions()==A 的贡献元组；format_providers 同理（给 A 一个伪 FormatProvider——`from mycad.formats.base import FormatProvider` 用 STEP_PROVIDER 或手写最小实例）。
- frozen：对 manager 实例赋值 → FrozenInstanceError。

### test_agent.py
- `import mycad.agent` 公开面：`set(dir(mycad.agent))` 中以非下划线开头的名字 ⊆ {Plan, PlannedCommand, <B0 勘察到的再导出>}（断言无多余公开符号）。
- agent 包零扫描守卫：walk `src/mycad/agent/*.py` 文本断言不出现 "import socket"/"import http"/"requests"/"openai"/"anthropic"/"schema_catalog"（小写化后子串比较）。
- mycad.plugins 公开面：六名齐且无多余（`from mycad import plugins` 后 dir 过滤）。

### evidence §T7b
追加到 .omo/evidence/task-7-phase0-mvp.md：交付物、四门、skipped 语义薄实现说明、deviations。

## 执行清单（按序，每步一回合）
- B0：六项前置读。
- B1：tests/plugins/__init__.py（空）+ test_types.py 首批。
- B2：test_types.py 追加完整 → 跑 → 红。
- B3：plugins/types.py 首批（常量+CommandContribution+PluginDiscoverer）。
- B4：types.py 追加（DiscoveredPlugin+PluginManifest）→ test_types 绿。
- B5：manager.py + plugins/__init__.py。
- B6：test_manager.py → 绿。
- B7：agent/plan_types.py + agent/__init__.py + test_agent.py → 绿。
- B8：scoped 四门全绿。
- B9：evidence §T7b + DoneClaim。

## scoped 四门（B8，.venv/bin/python）
1. `.venv/bin/python -m pytest tests/plugins/ -q` → 全 passed。
2. `.venv/bin/python -m basedpyright src/mycad/plugins/ src/mycad/agent/ tests/plugins/` → 0/0/0。
3. `.venv/bin/python -m ruff check src/mycad/plugins/ src/mycad/agent/ tests/plugins/` → 全过。
4. `.venv/bin/python -m ruff format --check src/mycad/plugins/ src/mycad/agent/ tests/plugins/` → 全过。

## DoneClaim（最后一条消息，仅 JSON 代码块）
```json
{"claim":"DoneClaim","slice":"T7b","deliverables":["<逐文件>"],"four_gates":{"pytest":"<N passed>","basedpyright":"0/0/0","ruff_check":"...","ruff_format":"..."},"deviations":["<每条一句>"],"notes":"<skipped 语义等实现选择>"}
```
