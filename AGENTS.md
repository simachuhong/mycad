# AGENTS.md — MyCAD 项目代理运行规则

本文件由 `/init-deep` 生成（基于 omo skill 流程 + 项目调研）。结构两段：
- **PROJECT KNOWLEDGE BASE**（上半段）：项目静态信息，开新会话先读这里
- **AGENT DISCIPLINE**（下半段）：运行经验教训，每条都是实测坑

---

## PONYTAIL OVERRIDE (项目级护栏)

`ponytail` skill（DietrichGebert/ponytail v4.13.0，MIT）已装在
`~/.config/opencode/skills/ponytail/SKILL.md`。**仅在显式触发时启用**，不要因为
上下文里偶尔出现 "yagni / 简化 / 一行能搞定吗" 就自动接管。

**触发方式**（任一）：
- 命令前缀：`/ponytail lite | full | ultra`（lite=推荐；full=默认激进；ultra=极端删除）
- 自然语言：`ponytail` / `be lazy` / `lazy mode` / `simplest solution` /
  `minimal solution` / `yagni` / `do less` / `shortest path`
- 退出：`stop ponytail` / `normal mode`

**硬保护 5 条路径**（ponytail 不可对这些路径提议简化；如提议必须拒绝并引用本节）：

| 路径 | 保护原因 |
|---|---|
| `src/mycad/core/` | T1 分层不变量：`tests/test_layering.py` 禁 `import build123d/OCP/numpy`；ponytail rung-3 「用 stdlib」看似无害但会破坏 core 与 geom 的职责边界 |
| `src/mycad/geom/` | src 中唯一允许引 CAD 后端的适配层；rung-4 「用原生平台」会诱惑把 OCCT 调用搬到 core，触发 layering test FAIL |
| `src/mycad/core/schema_v1.py` | `.mc.json` v1 审计六字段（id/version/params/ordinal/timestamp_utc/confirmed_by）由 ADR-002 锁定；rung-6 「能一行吗」会推 drop 字段，破坏持久化兼容 |
| `src/mycad/core/bus.py` | 唯一写入路径由 ADR-001 锁定；rung-1 「需要存在吗」会推直接改 Document，破坏 undo = 全量重放不变量 |
| `tests/test_layering.py` | 分层不变量本身的强制器；rung-7 「最小可工作代码」不得简化此测试，否则分层规则无人守护 |

**当 ponytail 提议触碰以上路径时的标准回应**：
> "blocked by MyCAD AGENTS.md PONYTAIL OVERRIDE; reason: <cite 表格一行>"

若用户**明确**要求对受保护路径做 ponytail 化（例如 "ponytail 一下 core/bus.py"），先**暂停**并向用户复述保护原因 + 询问是否真的要做；用户二次确认后再解除护栏。

---

## OVERVIEW

Ubuntu 22.04+ 桌面端开源 CAD（Apache-2.0）。阶段 0 = headless 可编程内核 MVP，以法兰件（φ80×8 / 4×φ6 PCD50）为验收牵引；UI（PySide6 壳）与 3D 预览后置到阶段 1。

- **几何内核**：OpenCascade（OCCT），经 `build123d==0.11.1` + `cadquery-ocp-novtk>=7.9.3.1.1,<7.9.4` 暴露
- **写入路径**：唯一 Command Bus；undo = 删命令 + 全量重放（ADR-001）
- **持久化**：`.mc.json` v1 = 纯 JSON 命令历史 + 审计六字段（ADR-002）
- **智能体**：阶段 0 = Plan 数据结构 + 六态机 + 确认红线（无 UI/Chat/MCP）；MCP 边界见 ADR-004
- **平台分层**：T1（ubuntu 22.04/24.04 x64 + windows）/ T2（信创 aarch64）/ T3（龙芯 go/no-go 阶段 1 末）
- **README 已过时**：README 写"应用程序代码未脚手架"，但 src/mycad/ 实质代码已就位（T7c 阶段）

## STRUCTURE

```
MyCAD/
├── src/mycad/
│   ├── app.py                # T7c 组合根：唯一允许同时引 mycad.core + mycad.geom 的 src 文件
│   ├── core/                 # 领域核心；T1 禁 import build123d/OCP/numpy
│   ├── geom/                 # build123d/OCP 适配层；src 中唯一允许引 CAD 后端的包
│   ├── commands/             # CommandSpec + registry + dispatch + demo + grammar
│   ├── builtin_commands/     # 阶段 0 八条 P0 内置命令（specs.py + defs.py）
│   ├── formats/              # 格式提供方；阶段 0 = STEP 只写产品化 + STL 只写 + STEP 测试辅助读
│   ├── plugins/              # entry-point 发现 + manifest + loader + manager
│   ├── cli/                  # mycad CLI：repl/run/validate/commands/plugins
│   └── agent/                # plan_types（阶段 2 智能体预留）
├── tests/                    # 镜像 src 结构；插件测试夹具在 tests/fixtures/plugins/
├── docs/
│   ├── 需求分析书.md / 技术路线.md / UI设计初稿.md
│   └── adr/                  # ADR-001..006（架构决策记录）
├── plugins_examples/mycad_plugin_demo/   # 最小插件示例
├── scripts/gen_baseline_hashes.py
├── pyproject.toml            # ruff + basedpyright + pytest + hatchling 配置
└── .omo/                     # 入仓：plan/evidence/boulder/ledger.jsonl
```

## WHERE TO LOOK

| 任务 | 入口 |
|---|---|
| 启动流程 | `src/mycad/app.py::build_app` → `src/mycad/cli/__main__.py::main` |
| 命令注册与派发 | `src/mycad/builtin_commands/specs.py`（八条 P0 spec）→ `core/bus.py` |
| 几何适配层 | `src/mycad/geom/kernel.py::BuildKernel`（进程级单例，`reset()` 由 `build_app` 独占） |
| 存档 / 重放 | `core/persistence.py` + `core/schema_v1.py`（`.mc.json` v1 schema） |
| 插件契约 | `plugins/manifest.py` + `plugins/types.py`，对照 `docs/adr/ADR-003.md` |
| 格式提供方 | `formats/providers/` + `formats/registry.py`，对照 `ADR-005` |
| 平台 / 依赖策略 | `ADR-006`（T1/T2/T3 分层） + `pyproject.toml` 依赖 pin |
| 测试规范 | `tests/test_layering.py`（layering 不变量是项目的元规则） |

## CODE MAP（关键类 / 唯一入口）

| 符号 | 文件 | 角色 |
|---|---|---|
| `build_app` | `src/mycad/app.py` | 组合根；返回 `AppServices(registry, kernel, formats, plugins)` |
| `BuildKernel` | `src/mycad/geom/kernel.py` | build123d 进程级单例；`reset()` 由 `build_app` 独占调用 |
| `CommandBus` | `src/mycad/core/bus.py` | 唯一写入路径；批事务 = 执行前快照、整体回滚 |
| `Document` | `src/mycad/core/document.py` | 真相源；有序命令历史 + 重放构造几何 |
| `CommandRegistry` | `src/mycad/commands/registry.py` | spec 注册表，按 id 去重 |
| `FormatProviderRegistry` | `src/mycad/formats/registry.py` | 优先级选择；`ProviderConflictError` 显式冲突 |
| `PluginManager` | `src/mycad/plugins/manager.py` | 插件命令贡献 + handler 覆盖 |
| `LoadedDocument` | `src/mycad/core/persistence.py` | Document + Bus 配对（`new_document()` 返回） |
| `PluginManifest` | `src/mycad/plugins/manifest.py` | `CURRENT_API_VERSION="1.0"` 主版本门控 |

## CONVENTIONS

- **T1 分层硬规则**（`tests/test_layering.py` 强制执行）：
  - `mycad.core/*` 禁 import `build123d` / `OCP` / `numpy`
  - `mycad.geom/*` 是 src 中**唯一**允许引 CAD 后端的包
  - `src/mycad/app.py` 是**唯一**同时引 `mycad.core.*` 与 `mycad.geom.*` 的文件
  - 测试中只有 `tests/geom/` + `tests/helpers/step_roundtrip.py` 可引后端
- **零类型抑制**：项目内 `# type: ignore` / `# pyright: ignore` 必须为 0（白名单 `tests/typing/` 不存在时违规则必现）
- **一规则一套**：ruff `E/F/W/I/B/UP/C4` 全树统一，不允许 per-file 忽略
- **改模型只能经 Bus**：任何修改 `Document` 的代码只能走 `CommandBus.submit()`，直改模型视为架构违规
- **每条命令必须可重放**：undo = 历史重放，命令必须为「参数 → 几何」纯函数；携带不可重放副作用即破不变量
- **存档 `.mc.json` schema**：UTF-8 JSON；顶层 `format/version/metadata/commands/named_groups`；命令审计六字段 `id/version/params/ordinal/timestamp_utc/confirmed_by`；修订留痕在 `amendments[]` 追加，**不覆盖原 timestamp**
- **坐标与单位**：全局右手笛卡尔，mm（长度） / mm³（体积） / 十进制度（`_deg` 后缀键名）；极阵列 `start_angle_deg=0` 对齐全局 +X（自 +Z 俯视逆时针）
- **格式提供方优先级**：默认 100；同扩展名多 provider 取最小值，相同则 `ProviderConflictError`（**不做隐式覆盖**）
- **插件 trust model**：任意 Python 插件 = 任意代码执行；`manifest.permissions` 仅声明不强制（ADR-003 R9）
- **SPDX 头**：所有 src/.py 文件首行 `# SPDX-FileCopyrightText: 2026 MyCAD contributors` + `# SPDX-License-Identifier: Apache-2.0`

## ANTI-PATTERNS（THIS PROJECT）

- ❌ `mycad.core/*` 加 `import build123d` → `test_src_has_no_backend_imports` 拦
- ❌ src 除 `app.py` 外同时 `from mycad.core import ...` + `from mycad.geom import ...` → `test_composition_root_is_the_geom_core_bridge` 拦
- ❌ 加 `as any` / `# type: ignore` / `# pyright: ignore` → `test_no_type_ignore_or_pyright_ignore_sites` 拦
- ❌ 为单文件加 ruff per-file ignore → 违反 T1 一规则一套
- ❌ 在 `core/bus.py` 之外直接改 `Document.feature_history` → 违反 ADR-001 唯一写入路径
- ❌ 写商业格式（JT/Parasolid/ACIS/sldprt/NX/CATIA）进核心 → 违反 ADR-005 商业墙
- ❌ 引入 mcp SDK / LLM 调用 / 网络调用代码到阶段 0 → ADR-004 阶段 0 零依赖
- ❌ 把 `.omo/cache/` `.omo/review/` `.omo/run-continuation/` 入仓 → 已 gitignore；只 plan/evidence/boulder/ledger 入仓
- ❌ 跳过用户确认直接执行命令 → 确认红线（需求 §6）；MCP 落地时由 `confirmation_token` 兜底
- ❌ 把 conda-forge 当主路径 → conda-forge 的 build123d 滞后 0.9.1 与锁定 0.11.1 不兼容（ADR-006 偏离 ①）；`uv sync` 才是主路径
- ❌ 占用未到阶段的命令 id（chamfer/shell/union/intersect/pattern_linear/mirror/draft/sweep/datum.*）→ 命名空间保留给未来（ADR-003 §9）

## COMMANDS

```bash
# 安装（锁定 uv.lock，不带锁重写）
uv sync

# 验证四门（增量跑，按改动路径收敛；全量只在最终集成时跑一次）
uv run ruff check <path>            # 单路径 lint
uv run ruff format --check <path>   # 格式检查
uv run basedpyright <path>          # 严格类型（pyrightconfig.json venvPath=.venv）
uv run pytest tests/<path> -q       # scoped 测试

# CLI 入口
uv run mycad                        # 默认 REPL
uv run mycad run script.txt         # 执行 ASCII 命令脚本
# 注：mycad validate/commands/plugins 阶段 0 尚未实现（cli/__main__.py 触发 not-implemented 退出码 2）

# 离线/企业网备选（清华/阿里源，仅完全无外网时使用）
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
uv sync
```

## NOTES

- **CI 三 job**（`.github/workflows/ci.yml`）：`ubuntu-22.04` / `ubuntu-24.04` / `windows-latest`；阶段 0 不含 aarch64 / 龙芯（ADR-006）
- **依赖硬 pin 理由**：`cadquery-ocp-novtk<7.9.4` 因 OCP 7.9.4 丢了 build123d 0.11.1 依赖的 TopoDS_Wire 修复
- **存档 v1 = 纯 JSON 命令历史**，不带 BREP 快照；快照缓存列为 v2 演进口（ADR-002 R17）
- **Plugin 命令贡献契约**（`mycad.commands` entry）：callable 返回 `list[CommandContribution(spec, handler_factory)]`；handler_factory=None 时由 `BuiltinModelingHandler` 兜底（适用声明式建模命令）；`demo.ping` 型非几何命令必须自带 handler
- **暂未实现的 CLI 子命令**：`validate` / `commands` / `plugins`（T10b/c 占位）—— 派发逻辑存在但 body 报 `not implemented yet`，退出码 2
- **基于类型化的严格级别**：`pyrightconfig.json` `typeCheckingMode=strict`；basedpyright==1.40.1 锁定

---

## AGENT DISCIPLINE（实测坑；保留自原 AGENTS.md）

### 工具陷阱

- **Read 工具截断长行**：超过 2000 字符的行会被截断。转写或派发前先用
  `awk 'length($0) > 2000 {print FNR}' <file>` 检查（必须用 `FNR`，`NR` 跨文件累计会误报行号）；
  长行内容用 bash `sed -n '<N>p'` 或 `cat` 取回。
- **bg id 不跨 opencode 重启存活**：后台任务 id 仅存在于运行实例内存。会话与消息持久存于
  `~/.local/share/opencode/opencode.db`（表 `message` / `part` / `session`），**session id 是持久键**，
  需要恢复交付或 DoneClaim 时直读 DB。

### 子代理派发可靠性

- **"Completed" 通知 ≠ 成功**：静默死亡会被系统误报为完成。验收三要素缺一不可：
  会话尾消息含 DoneClaim、磁盘存在交付物、scoped 验证命令复跑通过。
- **长推理停摆（已复现 4 次）**：glm-5.3 单回合内过长的内部推理会耗尽输出 token 预算，
  回合以零可见内容结束，循环正常退出（日志特征：`exiting loop` + `cancel`，会话尾消息仅有
  step-start + reasoning 部件）。`deep` 类人设鼓励深思，设计面大的任务高发；机械化任务不受影响。
- **缓解策略（按优先级叠加）**：
  1. 大任务拆分为顺序子任务，缩小单回合设计面；
  2. 增量纪律：每回合只写一个文件、小步推进、每回合必须落盘；
  3. 计划先外化：加载任务书后立即把执行清单写到 /tmp 下再机械执行，抑制长推理;
  4. 设计密集型任务优先 `unspecified-high` 类别而非 `deep`。
- **续接路径不可靠**：`task(task_id=...)` 对死亡/挂起会话的续接已实证失败（点火消息不进会话）；
  死亡会话一律全新派发。任务提示词应落盘暂存（如 `.omo/start-work/wave1-prompts/`），
  派发时由子代理第一动作 `cat` 自加载（同时避开 Read 截断）。
- **活性探测金标准**：周期性查 DB `message` 表 `COUNT(*)` + `MAX(time_created)`；
  30 分钟无新消息即判死亡，不必等超时收割，直接取消重派。

### 验证纪律（省配额）

- **验证一律增量/差异化**：路径级 scoped 命令（只碰改动路径），不重复跑全量；
  全量四门（ruff check / ruff format / basedpyright / pytest）只在最终集成时跑一次。
- **已 CONFIRMED 的任务不重跑**。
- **篡改探针**是对抗验证的有效手段：删除/改写交付物中的关键内容 → 测试必须 FAIL →
  还原 → 测试必须 PASS（红→绿闭环才作数）。
- 等待期间用长阻塞（单 bash = sleep ~590 + 最小化探测输出）覆盖时间，减少回合数。

### 事件记录

- 一切基础设施故障、根因诊断、修复与重派决策必须追加写入 `.omo/start-work/ledger.jsonl`
  （JSONL，一行一事件），包含对抗类探测结果与清理回执。
