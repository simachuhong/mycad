# phase0-mvp - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**你会得到什么：** 一个在命令行里就能用的参数化建模内核雏形——用英文命令脚本或 JSON 计划建出法兰这类零件（尺寸可改、自动重算），导出 STEP/STL，支持撤销、批失败整体回滚和存档再打开；同时插件、CAD 格式互转、MCP/PLM/CAE、国产平台这四条未来扩展线以 6 份架构决策文件把边界和接口一次性定死。整套能力已在本机用尖刺验证过（建模体积与数学解析解一致到浮点舍入量级）。

**为什么这样做：** 三份文档的共同地基是"一切建模操作都是可序列化、可撤销的命令"。阶段 0 不做界面，先用最小代价把"命令→校验→执行→撤销→导出"这条唯一写入路径打通并以验收法兰锁死；几何引擎整体封在一层适配器后面，因为所选 Python 几何库仍是 0.x 版本、有破坏性变更史，封层后升级或换库都不波及命令层与未来的界面/Agent。

**它不会做什么：**
- 没有图形界面（界面是下一阶段）；没有真正的 AI 助手（只留计划数据结构和确认流程的位置）。
- 不能读写 SolidWorks/UG/CATIA/JT 等商业格式（法律与授权墙，只能走未来持证第三方插件）；不做 DWG。
- 不做安装包、不做国产 CPU 的认证适配（本阶段只锁定平台分层与 glibc 基线，龙芯在阶段 1 末做可行性裁决）。

**Effort:** Medium
**Risk:** Medium - 主要风险是 OCCT 预编译包的版本/平台锁定与参数化改模型的拓扑断裂；两者均有实测证据、封层测试和谓词引用纪律兜底。
**Decisions I made for you:** 你最初的要求是开放式的"做规划"，以下默认由我按研究证据替你决定，你可否决其中任何一条：①本次计划只覆盖无界面的阶段 0，阶段 1–3 只给路线图锚点；②打包从文档设想的 conda 改为官方推荐的 pip+uv（有官方原文与本机实证）；③撤销采用"删命令+全量重放"而非反向操作；④几何引用一律用几何谓词（如"最大的 Z 向平面"），禁止裸面编号；⑤插件/MCP/PLM/CAE 阶段 0 只定接口与契约、不实现生态，MCP 的执行确认令牌只能由本机用户交互产生（远程 AI 无法绕过）；⑥CI 第一天就同时跑 Ubuntu 与 Windows，国产平台按 glibc≥2.31 分三层（统信 UOS V20 桌面版 glibc 2.28 明确列为不支持）；⑦CLI 语法保持英文 ASCII，中文留给未来界面。

Your next move: 审阅本计划；认可后显式发出开始指令（start）即进入实现，执行将按 9 个波次（W0–W8）推进并全程留证。在此之前计划会先经过独立缺口分析与双份高精度评审，评审不过会自动修订。完整执行细节见下文。

---

> TL;DR (machine): Medium effort / Medium risk —— headless 可编程建模 MVP：8 条 P0 命令+总线重放撤销+批回滚+历史参数编辑重放+JSON 存档+STEP 写/STL 写（STEP 读仅测试路径）+CLI+插件/格式扩展缝+6 份 ADR，三平台 CI（ubuntu-22.04/24.04、windows-latest），11 todo/9 波次（W0–W8）。

## Scope

阶段 0 = **可编程 MVP（headless，无 UI）**。以需求分析书 §8 法兰验收件（外径 φ80/内孔 φ20/厚 8/4×φ6 均布孔 PCD50）为牵引，打通唯一写入路径：

`命令 JSON/CLI → 校验 → Command Bus（undo=历史重放；批事务快照回滚）→ Document（有序特征历史+元数据）→ geom 适配层（build123d 0.11.1 / OCCT 7.9.3 封层）→ STEP/STL + JSON 存档 v1 + CLI`

并以"接缝 + 6 份 ADR"落用户的三点补充（插件/MCP/PLM/CAE、格式互转、跨平台+信创），阶段 1–3 仅路线图锚点。

### Must have

1. **C1 环境与工程骨架**：`git init`；`pyproject.toml`（src 布局、Python `>=3.12,<3.15`、**build123d 精确 pin `==0.11.1`、OCCT 绑定 patch 级 range `cadquery-ocp-novtk>=7.9.3.1.1,<7.9.4`（同为 OCCT 7.9.3 ABI）**、uv lock）；ruff + basedpyright（strict）+ pytest；GitHub Actions 矩阵恰好三个 job：**ubuntu-22.04 / ubuntu-24.04 / windows-latest**（`astral-sh/setup-uv` + `uv sync`；全计划凡提 CI 平台均以此三 job 为准，无任何"双矩阵"表述）；安装文档含国内镜像配置（R18）+ conda/wheelhouse 离线附录。
2. **C2 geom 适配层**（`src/mycad/geom/`）：8 条 P0 建模原语内核（box/cylinder/extrude/revolve/hole/hole_pattern(polar)/fillet/boolean_cut）；**几何谓词选择器**（JSON 描述子，禁裸索引，A6）；质量属性；可调弦差 tessellation；STEP/STL I/O。**OCP/build123d 类型绝不越过 geom 边界**（有强制测试）。
3. **C3 命令模型与注册表**（`src/mycad/commands/`）：CommandSpec（稳定 id + version + JSON Schema + 校验 + CLI 文案映射）；注册表驱动 CLI/未来 UI/Agent 三入口同源；8 条内置命令与 UI 初稿 §5.3 的 ID **逐字一致**（`feature.box/cylinder/extrude/revolve/hole/hole_pattern`、`modify.fillet/boolean_cut`）。
4. **C4 Document + Command Bus**（`src/mycad/core/`）：有序特征历史为唯一真相源；metadata（part_no/revision/material/source）；NamedGroup；headless 信号总线；undo/redo=删命令+全量重放（重放引用失效显式报错指向具体命令）；批事务=失败快照整体回滚；Plan 状态机 `draft|confirmed|executing|done|failed|cancelled`（纯函数，无 LLM）；JSON 存档 v1（`format/version` + 迁移钩子）。
5. **C5 CLI**（`src/mycad/cli/`，console script `mycad`）：ASCII 英文 REPL + 脚本文件；文本 ⇄ JSON 等价；`new/建模命令/undo/redo/history/save/open/export/validate/run/help/quit`；退出码 0/1/2；法兰脚本端到端。
6. **C6 质量与验收**：法兰 golden（体积 36794.3331588437±1e-6 mm³，真值=π·8·(40²−10²−4·3²)=36794.333158843656…；测试内以 `math.pi` 公式直算为唯一真值源，JSON 常量存全精度；bbox 80×80×8、6 圆柱面、1 solid）；STEP 导出→测试辅助读回体积一致；`examples/flange_script.txt` + `examples/flange_plan.json`；Apache-2.0 NOTICE 第三方归属、SPDX 头。
7. **C7 扩展缝**：importlib.metadata entry points（组 `mycad.commands`/`mycad.formats`）；贡献 entry 所在模块的 `manifest` 属性（callable/dict/dataclass，算法见 T7）→ id/version/api_version/permissions/homepage；API 主版本不兼容跳过且不影响核心；pre/post 命令与保存信号；插件=全信任（文档明示，不做沙箱）。
8. **C8 FormatProvider 缝**：对齐 OCCT DE_Wrapper 的 provider 注册表（name×vendor×priority、can_read/can_write、target=shape）；阶段 0 实现 STEP（**写**；读仅经 `tests/helpers/` 测试辅助函数用于导出件往返断言，**不做产品化读、不进命令历史**——F-DOC-03 导入是 P1/阶段 1）与 STL（只写）两个 provider；`priority: int`（默认 100，同扩展名多 vendor 取小值，priority 相同注册冲突报错）；导入三级枚举（DUMB_SOLID / ASSEMBLY_WITH_ATTRS / EDITABLE_FEATURES，外部格式永不到第三级）仅随枚举与 ADR 定义，阶段 0 无返回导入结果的产品路径。
9. **C9 跨平台纪律**：纯可移植代码（pathlib、UTF-8、无 POSIX 假设）；T1 三平台 CI（ubuntu-22.04/24.04、windows-latest）第一天就绪；ADR-006 锁定 T1/T2/T3 与 glibc≥2.31 基线。
10. **6 份 ADR**：`docs/adr/ADR-001` 命令总线与重放、`002` JSON 存档、`003` 扩展点与插件 API 版本、`004` MCP 边界（只写决策不实现）、`005` 格式提供方分级、`006` 平台分层。

### Must NOT have (guardrails, anti-slop, scope boundaries)

- **无 PySide6/Qt/任何 UI 代码**；不装 VTK；视口只到 tessellation 数据接口。
- **无真实 LLM 调用**、无网络调用代码、无 `mcp`/`ollama` 依赖；`agent/` 仅协议占位与 Plan 纯数据结构；MCP 只出 ADR-004。
- 不做 per-command inverse undo、不做 BREP 快照缓存（ADR-002 仅记录演进口）；不做 ElementMap/拓扑命名算法。
- 不实现草图约束求解器：extrude/revolve 的截面仅支持参数化 profile 描述子（circle/rect），不做自由草图。
- 不实现 IGES/glTF/3MF/DXF 等其余格式的 provider（ADR-005 给序列）；**绝不引入商业格式适配器代码**（JT/x_t/sat/sldprt/NX/CATIA），不碰 DWG/逆向库。**STEP 读不产品化**：无 `document.import_step` 历史节点、无导入相关异常的产品路径；STEP 读代码只能存在于 `tests/helpers/`。
- **不写任何工具 schema 生成代码**（无 `schema_tools.py`/`schema_catalog.py`/`tests/snapshots/`）；面向 Agent 的工具 schema 形态只在 ADR-004 文字与本计划附录 A（规范文档）中描述，阶段 2 才实现。
- 不做 PLM 检入检出/BOM、不做 mesher/CAE 求解/INP 导出；不做插件沙箱化；不做安装包（AppImage/Flatpak/msi）。
- 不引入 CadQuery、pythonocc-core（R15 双 OCCT 运行时冲突）；不用 `as any` 等价物（`# type: ignore`/`Any` 逃逸，basedpyright strict）。
- 不做 aarch64/QEMU/龙芯 CI 任务（ADR 记录，阶段 1 末 spike）；不重构/修改 `docs/` 三份基线原文（只新增）。
- 不写任何阶段 1–3 的产品代码锚点（接口只在 ADR 文字中描述）。

### 显式延期需求登记（非静默缺失，最终审计逐项核对）

| 需求 ID | 阶段 0 处置 | 落点 |
| --- | --- | --- |
| F-DOC-03 STEP 导入 | 仅 `tests/helpers/` 测试读回；产品化在阶段 1 | T8、ADR-005 |
| F-MOD-02 视口/预览、F-MOD-03 结构联动、F-MOD-04 显示模式、F-MOD-05 基准 | 阶段 1（PySide6 壳）；几何侧只交付 tessellation 数据接口。**注意：基线 `docs/需求分析书.md:157` 与 `docs/技术路线.md:104` 明确把"简单预览/简单 3D 预览"列为阶段 0 交付物，本计划将其后置——这是显式偏离（并入偏离②，记录于 ADR-001），不是遵循基线分期；视口本体（F-MOD-03/04/05）才是基线自身的阶段 1 项** | T2、ADR-001 |
| F-UI-01..06 全部界面需求 | 阶段 1 | 仅路线图（计划末） |
| F-AGT-01 真实 LLM 生成计划 | 阶段 2；阶段 0 仅 Plan 纯数据+状态机 | T6、ADR-004 |
| F-AGT-03 计划参数同步 UI | 阶段 1（UI）+ 阶段 2（Agent） | 路线图 |
| F-AGT-06 复杂 UI 命令共用确认管道 | 阶段 1（UI 管道）+ 阶段 2（Agent 接入）；阶段 0 的 headless 等价=Plan 六态+confirmed_by | T6、ADR-001/004 |
| F-TREE-01/PROP/OPT 结构树/属性/选项面板 | 阶段 1 | 路线图 |
| NF-06 可扩展 UI 三注册函数 | 后端命令/格式缝阶段 0 落地；UI 注册在阶段 1 | T9、ADR-003 |
| NF-07 Agent 生成代码沙箱 | 阶段 2；阶段 0 无 Agent 生成代码，ADR-003 明示插件=全信任、ADR-004 明示确认红线 | ADR-003/004 |
| 研究台账 A19 国产 LLM 路径（DeepSeek/通义云端 API 或 Ollama aarch64 本地；不绑境外 API，与信创网络协同） | 阶段 2 路线图假设，状态=accepted/future；阶段 0 无 LLM/无网络/无任何国内外 API 调用（NF-02 本地优先），仅交付 Plan 数据结构、状态机与 MCP/确认边界（ADR-004） | ADR-004、T6 |

## Verification strategy
> Zero human intervention - all verification is agent-executed.

- **Test decision: TDD**（测试先行），框架 pytest 8.x（uv 管理）。每个 todo 的验收测试先写或与实现同提交；Implementation+Test 永远是同一个 todo、同一个 commit。
- **静态质量门（每次提交必过，CI 强制执行）**：
  - `uv run ruff check src tests` 与 `uv run ruff format --check src tests`：零告警（ruff 配置见 T1）。
  - `uv run basedpyright`：strict 模式零错误；禁止 `Any` 逃逸与 `# type: ignore`（**#round12d-3 与 T1 豁免规则唯一化**：`# type: ignore`/`# pyright: ignore` 全仓唯一合法位置=`tests/typing/` 反例目录（见 T1 豁免段 #round9-9），`src/**` 与其余 `tests/**` 零 ignore；第三方无桩模块一律以 stub 文件（.pyi）解决而非 ignore——本条与 :174 是同一条规则的两处引用，不得另立"第三方白名单"）。
  - `uv run pytest -q`：全绿。
- **几何断言纪律**：golden 数值全部带容差（体积 `abs(diff) < 1e-6` mm³；bbox/尺寸 `1e-9` mm；面/体计数精确相等）；golden 期望值来源=解析公式（法兰：`math.pi*8*(40**2-10**2-4*3**2)` = 36794.333158843656…），**测试内直接用 math 公式计算，禁止手写 4 位小数值（36794.3332 与真值差 4.12e-5，超 1e-6 容差 41 倍），也不得从实现输出反录**；`tests/golden/flange_golden.json` 存两组全精度常量（Group A 36794.3331588437、Group B 68455.3039217216）并以 `_formula` 键记公式（JSON 无注释）。
- **平台门**：GitHub Actions 恰好三个 job——`ubuntu-22.04`、`ubuntu-24.04`、`windows-latest`，每 PR/推送跑 ruff+basedpyright+pytest；Windows 下的路径/编码/控制台用例是显式测试（见 T11）。
- **边界封层测试（防 slop 结构性守卫）**：
  - `tests/test_layering.py`：用 AST 扫描断言 `build123d`/`OCP`/`numpy` 的 import 只出现在 `src/mycad/geom/`、`tests/geom*` 与 **`tests/helpers/step_roundtrip.py`**（#round10-NB5：与 T2/T8 的白名单表述逐字一致，高级验证策略不得遗漏该测试辅助文件）；`core/commands/agent/cli` 的公开签名不出现这些类型。
  - `tests/test_seams.py`：entry-point 插件 API 版本不兼容时被跳过且核心仍可加载、注册表可列举；插件异常被隔离不拖垮核心。
- **往返门**：STEP 导出→经 `tests/helpers/` 测试辅助函数读回，solid 数与体积一致（该读回路径**仅供测试**，不是产品功能；产品化 STEP 导入 F-DOC-03 在阶段 1，ADR-005 注明）；存档 JSON save→open 后全量重放，几何断言与保存前一致。
- **证据落盘**：每个 todo 把 QA 命令与输出摘要写入 `.omo/evidence/task-<N>-phase0-mvp.md`（含命令行、关键断言、CI run URL 或本地运行时间戳）；无证据不得标记完成。
- **验收件端到端**：`uv run mycad run examples/flange_script.txt` 与 `uv run mycad run --json examples/flange_plan.json` 两条路径都必须产出同一 golden 几何（体积/bbox/面数一致）与有效 STEP/STL，然后 undo 批次回退成功。

## Execution strategy

11 个 todo，9 个波次（W0–W8）。每波内可并行派发独立执行代理；波次间严格按依赖矩阵。**波次顺序按文件同写冲突与 import 依赖排定**：T8 是 T7 app.py 的构造依赖（build_app 要 import 具体 FormatProviderRegistry），故 T8 必须先于 T7 单独一波；T9 要改 T7 的 app.py 组合根，不能同波。所有代理只写产品代码与测试（规划师不写）；每个 todo 完成后必须过静态门+测试门并落证据，再进下一波。

### Parallel execution waves

- **Wave 0（地基，1）**：T1 工程骨架/打包/三平台 CI（ubuntu-22.04/24.04、windows-latest）/质量门/**阶段 0 异常全集 exceptions.py（闭合清单的唯一 owner，恰好 15 类）**。
- **Wave 1（三并行）**：T2 geom 内核（原型体+三模式布尔+谓词查询+质量属性+tessellation+封层）；T3 命令框架（CommandSpec 含 undo_compensation 字段/Schema 子集含 oneOf+$ref+$defs/校验/注册表/CLI 语法映射规则）；T4 六份 ADR。
- **Wave 2（1）**：T5 geom 特征层（extrude/revolve 参数化截面、hole、极阵列孔、fillet）。
- **Wave 3（1）**：T6 core（Document/命令处理器契约/历史参数编辑重放/Bus/批事务/信号/存档 v1/Plan 状态机纯函数；Kernel 与 FormatResolver 以 Protocol 倒置，不 import geom/formats）。
- **Wave 4（1）**：T8 FormatProvider 注册表 + STEP 写/STL 写 provider（STEP 读仅 tests/helpers）；**先于 T7**，因为 T7 的 build_app() 要构造它。
- **Wave 5（1）**：T7 八条内置命令接线 + 组合根 app.py（import T8 的具体注册表并构造注入；id 逐字对齐 UI 初稿 §5.3）。
- **Wave 6（1）**：T9 插件缝（entry_points 发现、manifest、api_version 门控、权限声明、信号钩、demo 命令处理器；接线进 T7 的 app.py，故单列一波）。
- **Wave 7（1）**：T10 CLI（REPL+脚本、退出码、文本⇄JSON 等价；CLI 是顶层组合根，按扩展名解析 provider 做 export/open）。
- **Wave 8（1）**：T11 法兰 golden/双格式 examples/端到端/NOTICE/README/Windows 用例；随后 Final verification wave。

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| T1 | — | T2,T3,T4,T6（工程设施+异常清单） | — |
| T2 | T1 | T5,T8 | T3,T4 |
| T3 | T1（异常清单） | T6,T7,T9 | T2,T4 |
| T4 | T1 | 无（文档可滞后参考） | T2,T3 |
| T5 | T2 | T6,T8 | 无 |
| T6 | T3,T5（集成测试用真实特征原语） | T7,T8,T9,T10 | 无 |
| T8 | T5（geom 导出原语）,T6（FormatResolver Protocol/只读导出约定） | T7（build_app 构造依赖）,T10,T11 | 无 |
| T7 | T3,T5,T6,T8（import T8 注册表） | T9（app.py 同文件）,T10,T11 | 无 |
| T9 | T3,T6,T7（改 T7 产出的 app.py）,T6 处理器契约 | T10（插件 CLI 列举） | 无 |
| T10 | T7,T8,T9 | T11 | — |
| T11 | T10（examples/end-to-end）；T1 全程 CI | Final wave | — |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->

- [x] 1. T1 工程骨架：git + uv/pyproject + 严格质量门 + 三平台 CI + 安装文档 + **阶段 0 异常全集** + **中立几何 DTO** + **中立谓词描述子**
  What to do / Must NOT do:
  - 仓库根 `git init`；`.gitignore` 含 `.venv/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`*.egg-info/`、`dist/`、`build/`；**#round10-2 验收产物路径必须逐字忽略**（T10/T11 端到端与 F3 手动 QA 会在仓库工作树生成）：根目录 `flange.step`、`flange.stl`、`flange.mc.json`，以及 `examples/flange_plan.step`、`examples/flange_plan.stl`、`examples/flange_plan.mc.json`（六个路径逐行列入；`examples/` 下手工编写的 `flange_script.txt`/`flange_plan.json` 仍须提交，不得整目录忽略）；**`.omo/` 必须提交**（计划工件）；evidence 目录例外规则在 .gitignore 注释说明。
  - `pyproject.toml`（PEP 621 + hatchling，src 布局）：name=`mycad`，requires-python=`>=3.12,<3.15`；dependencies：`build123d==0.11.1`（**精确 pin**：0.x 有破坏性变更史，升级走独立 spike+golden 重放，R14）、`cadquery-ocp-novtk>=7.9.3.1.1,<7.9.4`（**patch 级 range 而非精确 pin**：7.9.3.x 同为 OCCT 7.9.3 的 ABI 兼容补丁发布，允许补丁内安全修复；锁定 7.9.4 排除下一 OCCT  minor——该理由以注释写在 pyproject 该行上方）；**禁止** CadQuery/pythonocc-core/PySide6/VTK/mcp 进依赖。dev dependency-groups：`ruff`、`basedpyright`、`pytest>=8`、`pytest-cov`（覆盖率仅报告不门控）。
  - ruff 配置：target-version py312，select=`E,F,I,N,UP,B,SIM,RET,PT,PL`，line-length=100，known-first-party=`mycad`。**basedpyright 严格配置（#round8-1，固定且已验证的配置，执行者零决策）**：写 `pyrightconfig.json`，内容逐字为 `{"include": ["src", "tests"], "typeCheckingMode": "strict", "venvPath": ".", "venv": ".venv"}`（`typeCheckingMode` 是 pyright/basedpyright 官方支持的顶层键，禁止使用臆造的 `strictList`/`strict` 列表键）；dev 依赖固定 `basedpyright==1.40.1`（2026-09-17 PyPI 核实的最新版；执行时若该补丁版已下架可用同 1.40.x 并在证据中说明，禁止留 `>=` 范围）；T1 QA 必须实际执行 `uv run basedpyright` 并以退出码 0 证明配置被加载（输出存证据），禁止"版本不符时查文档自行修正"的开放式回退。pytest testpaths=`["tests"]` addopts=`-ra --ignore=tests/typing`（#round11-6：tests/typing/ 是纯静态反例目录、含运行时必失败代码，pytest 必须排除收集；basedpyright 仍经 pyrightconfig include=["src","tests"] 扫描该目录，两通道互不干扰）。
  - `uv.lock` 提交；占位 `src/mycad/__init__.py`（`__version__ = "0.1.0"`，文件头两行固定为 `# SPDX-FileCopyrightText: 2026 MyCAD contributors` 与 `# SPDX-License-Identifier: Apache-2.0`；全项目 .py 文件统一此头）与 `tests/test_smoke.py`（断言版本）。
  - **SPDX 头自动化验收（#round8-5，NF-05 不靠人眼）**：本 todo 同时交付 `tests/test_spdx.py`：用 pathlib 递归枚举 `src/**/*.py`、`tests/**/*.py`、`scripts/**/*.py`、**`plugins_examples/**/*.py`（#round9-NB：demo 插件虽不进 wheel，其 .py 同样必须带固定 SPDX 头；该目录在 T9 之前不存在时与 scripts 同样显式断言跳过而非隐式忽略，T9 落地后扫描自动生效）**（scripts 目录不存在时显式断言跳过而非隐式忽略，T8 之后该目录随 gen_baseline_hashes.py 出现），逐文件断言**前两行逐字等于**固定两行 SPDX（行序固定，无 BOM、无前导空行）；fixture 反向自证：在 tmp_path 造一个缺头/两行顺序颠倒/年份写错的 .py，扫描函数必须报告；该测试纳入默认 `pytest -q` 与四门质量门；后续每个 todo 新建 .py 即被此测试强制覆盖。
  - **`src/mycad/core/exceptions.py`（闭合清单，本 todo 是唯一 owner，T2/T3/T5/T6/T8/T10 只消费、不新增类——确需新增必须先回本计划改清单）**：`MycadError(RuntimeError)` 唯一基类（构造统一 `message: str`，需要命令上下文的子类追加 `command_id: str | None=None`），阶段 0 全集恰好 15 个：
    1. `ValidationError`（参数校验，字段点路径入 message）2. `TopologyReferenceError(command_id, descriptor_json, reason, ordinal: int | None = None)`（**ordinal 显式字段（#round7-5）**：交互/单命令路径 None；Bus 重放、execute_batch、undo/redo、edit_and_replay、open_document 自动重放路径必须传入当前命令 ordinal——禁止只塞进 message 字符串）3. `GeomVersionError(expected, actual)` 4. `GeometryBuildError(command_id, reason, occt_summary, ordinal: int | None = None)`（ordinal 规则同上；geom 层直接构造时为 None，由 Bus 重放包装时补 ordinal）5. `CommandConflictError(conflicting_id)`（**仅用于命令 id 冲突**）6. `EmptyGeometryError(operation)` 7. `ArchiveVersionError(path, found, supported)` 8. `UnknownFormatError(extension_or_path)` 9. `CliSyntaxError(token_or_position, suggestion)` 10. `InvalidPlanTransition(from_status, requested)` 11. `InvalidHistoryError(action)` 12. `BatchRollbackError(failed_ordinal, failed_command_id, reason, executed_ids: tuple[str,...])` 13. `ReplayDuringRollbackError(original: Exception, replay_reason: str)`（**重放二次失败的通用包装**：批回滚 _rebuild 失败时 original=BatchRollbackError；编辑历史参数重放失败时 original=触发命令的 GeometryBuildError/TopologyReferenceError；保留两者信息）14. `UnknownCommandError(identifier: str)`（**#round11-NB2 构造参数名与语义唯一**：identifier=未命中的命令 id 或动词别名原文，由抛出点如实传入；T3 注册表按 id 未命中、T3 动词解析层按 verb 未命中共用同一异常与同一参数名，消息含最接近建议；列入全集防止 T3 私造；open 重放缺处理器时由 Bus 补 ordinal 到 message，签名不加 ordinal 字段）15. `ProviderConflictError(extension: str, provider1: tuple[str,str], provider2: tuple[str,str])`（**仅用于 FormatProvider 同 priority 且扩展名重叠**，后两者为 (name, vendor) 元组）。
   - **异常字段锁定测试（#round7-5）**：`tests/test_exceptions.py` 除"恰好 15 类+全 issubclass MycadError+两冲突异常签名不通用"外，增加：dataclasses.fields/inspect.signature 断言 `GeometryBuildError` 与 `TopologyReferenceError` 均含 `ordinal` 字段且默认 None；T6 测试中 batch/undo/edit/open 四路径失败直接 `assert exc.ordinal == <int>`（不靠 message 匹配）；直接 geom 调用路径断言 ordinal is None。
    **明确不设** `ImportSourceMissingError`（阶段 0 STEP 读仅测试路径，用内置 `FileNotFoundError`）。`tests/test_exceptions.py` 断言恰好这 15 个类名、全部 issubclass MycadError、且无 `__init__.py` 外的重复定义路径；另断言 `CommandConflictError` 与 `ProviderConflictError` 构造签名互不通用（防止混用）。
  - **`src/mycad/core/geometry_types.py`（中立几何 DTO，本 todo 是唯一 owner；前移至 Wave 0 以消除 T2→T6 隐藏依赖——T2 geom 与 T6 core/ports 均依赖之）**：仅标准库 dataclass，零第三方 import。三个 frozen dataclass，字段写死、执行者不得增减/改名：
    1. `MassProperties` 恰好五字段：`volume: float`（mm³）、`solid_count: int`、`cylindrical_face_count: int`、`bbox: BoundingBox | None`、`center_of_mass: tuple[float, float, float]`（空实体时为 (0.0, 0.0, 0.0)）。
    2. `BoundingBox` 恰好六字段：`xmin: float, ymin: float, zmin: float, xmax: float, ymax: float, zmax: float` + 两只读属性 `size -> tuple[float,float,float]`（=(xmax-xmin, ymax-ymin, zmax-zmin)）、`center -> tuple[float,float,float]`。
    3. `Tessellation` 恰好两字段：`vertices: tuple[tuple[float,float,float], ...]`、`triangle_indices: tuple[tuple[int,int,int], ...]`（构造时断言所有索引 < len(vertices)，否则 ValueError）。
  - `tests/core/test_geometry_types.py`（T1 即建 tests/core/ 目录）：用 `dataclasses.fields` 对三个类断言字段名元组逐字相等（防 CAE 缝漂移）；构造一组样例 DTO 断言 size/center 数值、空 COM 默认、Tessellation 越界索引 ValueError；basedpyright strict 通过。
  - 依赖方向（写进 T1 docstring 与 T2/T6）：geom 与 core/ports 单向 `from mycad.core.geometry_types import ...`；**geometry_types 不得 import geom/commands/formats**（layering 守卫已覆盖 geom 反向，另在 T1 测试断言本模块 `sys.modules` 无 build123d/OCP/numpy）。
  - **`src/mycad/core/selectors.py`（中立谓词描述子数据类，本 todo 是唯一 owner；前移至 Wave 0 以消除 T6 `core/groups.py` 对 geom 的隐藏依赖——core 永不 import geom）**：仅标准库 dataclass/typing，零第三方 import。两个 frozen dataclass + 阶段 0 字面量类型，字段写死、执行者不得增减/改名：
    1. `FaceSelector(surface: Literal["plane", "cylinder"], axis: Literal["+X", "-X", "+Y", "-Y", "+Z", "-Z"] | None = None, rank: int | None = None)`——**结构上无 index 字段**；`axis=None` 是 Python 侧唯一"未指定"表示（JSON 空串 `""` 仅 cylinder 分支合法，T3 `normalize_params` 删除该键，dataclass 由缺键得到 None、永不接收空串；wire 形态=键省略，绝不写 null，#round9-3）。
    2. `EdgeSelector(parent_faces: tuple[FaceSelector, ...], curve: Literal["line", "circle"] | None = None)`——结构上无 rank 字段（阶段 0 fillet 对 parent_faces 解析出的全部边生效）。
  - `tests/core/test_selectors.py`：`dataclasses.fields` 逐字锁定两字段名元组；构造默认值、frozen（赋值抛 FrozenInstanceError）、`""` 不被接受为 axis 合法值（运行时 Literal 不强制，断言由规范化层保证——本测试只锁数据形态）；断言本模块 `sys.modules` 无 build123d/OCP/numpy。**几何解析函数（resolve）不在本模块**：T2 的 `geom/selectors.py` 从 core import 这两个数据类并实现全部解析语义（过滤/排序/rank/异常），geom 侧可 `from mycad.core.selectors import FaceSelector, EdgeSelector` re-export 以保持 `mycad.geom.selectors.FaceSelector` 导入路径可用，但**定义只在 core 一处**（layering 守卫配合：tests 用 AST 断言 dataclass class 定义仅出现在 core/selectors.py）。
  - README 增补（保留原文）：开发环境 `uv sync`；国内镜像小节给 `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple` 与阿里镜像两种写法；附录 conda/离线 wheelhouse 备选（注明 conda-forge build123d 滞后 0.9.1，仅离线应急）。
  - `.github/workflows/ci.yml`：**完整 YAML 写死（#round8-6，执行者不得自行选 action）**，矩阵与 Python 安装方式逐字如下——
    ```yaml
    name: ci
    on: [push, pull_request]
    jobs:
      test:
        runs-on: ${{ matrix.os }}
        strategy:
          fail-fast: false
          matrix:
            os: [ubuntu-22.04, ubuntu-24.04, windows-latest]
        steps:
          - uses: actions/checkout@v4
          - uses: astral-sh/setup-uv@v4
            with:
              python-version: "3.12"
              enable-cache: true
          - run: uv sync --frozen
          - run: uv run ruff check .
          - run: uv run ruff format --check .
          - run: uv run basedpyright
          - run: uv run pytest -q
    ```
    Python 3.12 由 `setup-uv` 的 `python-version` 输入负责安装（该 action 内置托管 Python 下载，不另设 setup-python；禁止依赖 runner 默认解释器——ubuntu-22.04 默认是 3.10）；CI runner 用官方 PyPI 不设镜像。T1 验收脚本化（不引第三方 YAML 依赖）：在 `tests/test_ci_workflow.py` 用 pathlib+正则断言 workflow 文本同时包含 `ubuntu-22.04`/`ubuntu-24.04`/`windows-latest` 三 os、`astral-sh/setup-uv@v4`、`python-version: "3.12"`、四步质量门（ruff check/ruff format --check/basedpyright/pytest -q）。
  - **基线文档指纹（供 T11 `tests/test_scope_audit.py::test_tree_boundaries` 消费）**：初始提交①（baseline docs 快照）完成后，在 T1 工程骨架提交中生成 `tests/fixtures/baseline_doc_sha256.json`，键为三份基线文档相对路径（`docs/需求分析书.md`、`docs/技术路线.md`、`docs/UI设计初稿.md`），值为 sha256 hex；用标准库 hashlib 一次性脚本生成（脚本落 `scripts/gen_baseline_hashes.py` 可复跑，不依赖第三方）；T1 测试 `tests/test_baseline_hashes.py` 断言该 JSON 三键齐全且与当前 docs/ 实测 hash 逐字相等（本测试在 T1 时即绿，后续任何 todo 改了基线原文立即变红）。
  - Must NOT do：不以 conda 为主路径；不装 Qt/VTK/mcp/CadQuery/pythonocc；不改 README 现有许可段落；不做安装包；不提交 .venv；不放宽 strict；**豁免规则写死（#round9-9，消除"全项目零 type:ignore"与 T6 `tests/typing/` 反例的矛盾）：`# type: ignore`/`# pyright: ignore` 注释在整个仓库中唯一合法位置是 `tests/typing/` 目录——该目录用于存放"应当被静态检查拒绝"的反例对照文件（如 `expect_errors.py` 内 `# pyright: ignore[reportArgumentType]` 标记的表外字符串赋值；**#round11-6：文件名禁止 `test_*` 前缀，配合 pytest addopts `--ignore=tests/typing` 双保险确保 pytest 不收集——该文件含运行时必失败代码，被收集导入即套件失败；SPDX 头守卫照常覆盖该 .py**），basedpyright 仍扫描该目录，ignore 注释本身是反例语义的一部分；除此之外 `src/**` 与 `tests/**`（含 tests/typing 以外全部测试）零 ignore 注释、零 `Any` 逃逸；`tests/test_layering.py` 增加 AST 断言：全仓 ignore 注释所在文件路径必须以 `tests/typing/` 为前缀（反向自证：在 src 放一条 ignore 必须变红）；F2 引用同一规则**；**异常类不在此文件之外另行定义**。
  Parallelization: Wave 0 | Blocked by: 无 | Blocks: T2–T11 全部
  References (executor has NO interview context - be exhaustive):
  - `.omo/drafts/phase0-mvp-research-ledger.md` §2（Ubuntu 24.04.4 / Py 3.12.3 / 有 uv / 无 conda / 无系统 OCCT）、A2、A3、A9、A11、A12、E1（PyPI README 原文 "pip recommended for most users"；cadquery-ocp-novtk 7.9.3.1.1 = OCCT 7.9.3，cp312 manylinux_2_31_x86_64 + win_amd64 wheel；ubuntu-22.04=glibc 2.35≥2.31 满足 wheel 基线）、E11（46 包、OCP wheel 64.3MiB、镜像必要）、R13、R14、R18
  - `docs/技术路线.md:89-95`（基线 conda 建议已被 E1 证据推翻；偏离原因写入 T4 的 ADR）、`:127-151`（目录；在 ui/agent 之外新增 cli/formats/plugins 子包，ui/ 在阶段 0 不创建）
  - `docs/需求分析书.md:122-132`（NF-01 平台、NF-05 合规）、`:176-180`（依赖假设）
  - 可复现命令序列：`uv venv && uv pip install build123d==0.11.1`（已实证）；**尖刺证据已入库 `.omo/evidence/spike/`（#round7-NB5：flange_spike.py/fillet_probe.py/flange.step/flange.stl 为仓库内权威副本，执行者以该路径为准；下文出现的 `/tmp/opencode/mycad-spike/...` 是原始取证位置，两者内容一致）**
  Acceptance criteria (agent-executable):
  - `git log --oneline` 存在 T1 提交；`uv sync --frozen` 成功；`uv run python -c "import build123d,OCP;print(build123d.__version__)"` 输出 `0.11.1`。
  - `uv run ruff check . && uv run ruff format --check . && uv run basedpyright && uv run pytest -q` 四条退出码全 0。
  - `.github/workflows/ci.yml` 通过 YAML 解析且矩阵恰好含 3 个 os；有远端时三个 job 均绿（run URL 入证据）；无远端时在证据中明确记录"远端未配置，workflow 已就绪待首次推送"，且**禁止在任何后续证据/交付简报中声称双/三平台已验证**——未实测的 Windows 只能标"就绪未实测"，直到 F3 取得真实 run URL。
  - `tests/test_exceptions.py` 绿（15 类闭合清单断言）；`tests/test_spdx.py` 绿（#round8-5，含反向自证）；`tests/core/test_geometry_types.py` 绿（DTO 字段逐字锁定）；`tests/core/test_selectors.py` 绿（谓词描述子字段逐字锁定、frozen、无第三方依赖）；`tests/test_baseline_hashes.py` 绿（三键齐全且与 docs/ 实测 hash 相等）；`tests/test_ci_workflow.py` 绿（#round8-6，三 os+python-version 3.12+四步门）；**ignore 位置守卫绿（#round9-9）**：AST 扫描全仓 `# type: ignore`/`# pyright: ignore` 注释仅允许出现在 `tests/typing/` 路径下，初始无该目录时断言为 0 处（T6 建目录后仍须全部命中前缀白名单）。
  QA scenarios (name the exact tool + invocation):
  - happy：bash 顺序执行上述四条质量门，全绿；输出（含 `uv lock` 解析出的 build123d/cadquery-ocp-novtk 版本行）存 `.omo/evidence/task-1-phase0-mvp.md`。
  - failure（验证门有效后还原）：临时加未用变量 → `ruff check` 必须非 0；临时加 `x: any = 1`（小写 any 触发类型错误/严格告警）→ basedpyright 必须非 0；在 exceptions.py 临时加第 16 个类 → test_exceptions 必须红；失败输出附证据后 `git checkout -- .` 还原并重跑全绿。
  Commit: Y | `chore(engineering): uv/pyproject skeleton, closed exception taxonomy, strict quality gates, three-os CI`

- [x] 2. T2 geom 内核适配层：build123d 封层 + 谓词选择器 + 中立 DTO/查询/tessellation
  What to do / Must NOT do:
  - `src/mycad/geom/kernel.py`：**geom 包是全产品代码中唯一可 import build123d/OCP 的包**（包内拆分数量不限：kernel.py/selectors.py/_b123_ops.py/io 等均可，统一规则由 `tests/test_layering.py` AST 守卫按包边界判定，见下）；import 时断言 build123d 版本（**只用标准库，禁止引入 `packaging` 依赖**：`importlib.metadata.version("build123d")` 取版本字符串，解析为整数元组与期望 `(0, 11, 1)` 比较；解析失败/不匹配一律抛 `GeomVersionError`，消息含实际与期望版本；版本断言同时在测试中 monkeypatch `importlib.metadata.version` 返回 `"9.9.9"` 与 `"0.11"` 两个失败分支）；类 `BuildKernel`：`reset()`、`apply(command_id: str, params: Mapping[str, object]) -> None`（**T2 完整实现 feature.box 与 feature.cylinder 的全部三种 mode：new/add/cut**——经 build123d builder 的 `Mode.NEW/ADD/SUBTRACT` 映射，尖刺已实证 `Cylinder(10,20,mode=Mode.SUBTRACT)` 与 `Box(...,mode=Mode.SUBTRACT)` 体积正确（见 References）；add 用于两实体叠加，cut 用于以同形原型体从当前实体减料；**这两条命令的 mode=cut 归属 T2，T5 不再补做**；modify.boolean_cut 的通用内联工具差集仍在 T5）。封层公开面保持最小且**不含读文件操作**：reset/apply/mass_properties/tessellate/export_step/export_stl（后两者 T8 接线时在 geom 内 io 模块实现，签名本 todo 在 Protocol 中先占位 raise NotImplementedError）；**无 `import_step`/任何读文件公开方法**（STEP 读仅 `tests/helpers/` 测试辅助，见 T8）；**build123d Part 对象绝不离开 geom 包，不向 formats/core 返回任何几何句柄**。
  - `src/mycad/geom/selectors.py`：**谓词描述子数据类（FaceSelector/EdgeSelector）的唯一定义已由 T1 前移至 `src/mycad/core/selectors.py`**（geom 单向 import core，可 re-export 保持导入路径，但禁止重复定义；字段与无 index/无 rank(Edge) 结构纪律见 T1）。本模块只实现**几何解析**：schema 中 axis 的空串 `""` 的唯一处理规则（仅 cylinder 分支合法，T3 `normalize_params` 删除该键，Python 侧由缺键得 None；wire 省略键、禁 null，#round9-3）在 T3 完成，geom 只接收已规范化的 dataclass/dict（用 `.get("axis") is None` 判定）；解析经 build123d 代数选择器（`.faces().filter_by(GeomType...)`、按法向过滤、`group_by(Face.area)[-1].sort_by(Axis.X)[-1]` 习语）；失败抛 `TopologyReferenceError(command_id, descriptor_json, reason)`。
  - **FaceSelector 解析语义（写死，零判断空间；`resolve(selector, part, command_id) -> Face`，执行者不得另立规则）**：
    1. **过滤**：surface=`plane` → 仅平面；surface=`cylinder` → 仅圆柱面。axis 几何含义：plane 时轴=面外法向方向；cylinder 时轴=圆柱中心轴方向（**圆柱轴无向，+Z 与 −Z 视为等价匹配**，但 `+X` 不匹配轴向 Z 的圆柱面）。
    2. **axis 必填规则**：surface=`plane` 时 axis **必填**（六个带符号值之一；None/空串 → ValidationError，消息指明平面法向必须显式）；surface=`cylinder` 时 axis 可空（None=实体上全部圆柱面）或给带符号轴值（按无向规则匹配）。
    3. **排序（确定性全序）**：过滤后的候选面依次按 ①面积 `Face.area` 降序；②面积相等时按面心坐标字典序升序（x，再 y，再 z，全部用 float 直接比较，不做容差归并）排序；build123d 的 `group_by(Face.area)`/`sort_by(Axis.*)` 是实现手段，但**最终全序必须与本规则等价**，以专用测试锁定（构造两个等面积面验证字典序平局规则）。
    4. **rank 规则**：rank 给定时取排序后第 rank 个（0 起）；`rank < 0` 由 schema minimum 拒绝，`rank >= 候选数` → TopologyReferenceError（reason 含候选数与请求 rank）。rank 省略（None）时：候选恰好 1 个面则取该面；候选 0 个或 ≥2 个 → TopologyReferenceError（reason 分别为 "no-match"/"ambiguous" 加候选数；歧义绝不静默取第 0 个）。
    5. **面类型/轴不匹配**（如对全平面实体选 cylinder、或 axis=+Z 但无 +Z 法向平面）→ TopologyReferenceError（reason="no-match"，descriptor_json 回显）。
    6. EdgeSelector：先解析全部 parent_faces（任一失败即 TopologyReferenceError）取其边并集（保序去重），curve 非空时按 line/circle 过滤；同样的面积无关全序（边长降序+中点字典序）与 rank 语义在 EdgeSelector 上对称适用（EdgeSelector 结构无 rank 字段，阶段 0 fillet 对 parent_faces 解析出的**全部**边生效，见 T5；curve 过滤后为空集 → TopologyReferenceError）。
  - `src/mycad/geom/query.py`：`mass_properties() -> MassProperties`——**MassProperties/BoundingBox/Tessellation 三个中立 DTO 的唯一定义在 T1 已创建的 `src/mycad/core/geometry_types.py`（geom 单向 import core，与 exceptions 同方向），geom 不得重复定义**（字段见 T1：MassProperties 五字段、BoundingBox 六字段+size/center、Tessellation vertices/triangle_indices）；geom 负责把 build123d 测量结果填进这些 DTO，**numpy 类型不跨 geom 边界**（显式 float()/tuple() 转换）。`tessellate(linear_tolerance_mm: float, angular_tolerance_deg: float) -> Tessellation`：仅内存数据——**不写任何文件格式、不碰 OpenGL/渲染**，视口是阶段 1。
  - 空几何语义（全项目统一）：reset 后/无实体时 mass_properties 返回 solid_count=0、volume=0.0、bbox 为 None（不是异常）；对空几何做导出由 T8 抛 `EmptyGeometryError`。
  - 异常：**只消费 T1 创建的 `src/mycad/core/exceptions.py` 闭合清单**（15 类全集见 T1，本 todo 用到 ValidationError 之外的 TopologyReferenceError/GeomVersionError/GeometryBuildError/EmptyGeometryError 均已在清单内）；geom 单向 import core.exceptions，**不在 geom 内新增异常类**；**core 任何模块不得 import geom**。
  - 约定（写 docstring）：单位 mm、十进制度；Cylinder 中心在原点跨 z∈[-h/2,+h/2]（与尖刺一致）；布尔模式枚举 new|add|cut。
  - `tests/geom/`：box/cylinder 三模式体积解析对比；谓词在手工法兰形几何上选出 6 圆柱面/最大平面；**FaceSelector 解析矩阵（参数化穷举）**：①(plane,+Z) 对法兰选出最大端面（rank=0）；②**等法向多面构造体（#round9-2，禁止再用单个 Box10³ 测歧义：Box 只有 1 个 +Z 外法向平面）**：用 `Box(10,10,10,align=(Align.MIN,Align.MIN,Align.MIN)) + Box(20,20,5,align=(Align.MIN,Align.MIN,Align.MIN))` 之类两块沿 Z 底面共面、顶面不同高的叠加体（或等价构造，测试代码注释说明"两个 +Z 外法向水平面、面积不同"），`(plane,+Z)` 返回恰好 2 候选，省略 rank 必须 TopologyReferenceError(ambiguous)；③对同一构造体 `(plane,+Z),rank=1` 取面积第二大平面（小方块顶面），与直接代数选择结果逐面对等；④rank=99 → TopologyReferenceError 且 reason 含候选数；⑤(cylinder,None) 选全部圆柱面（法兰 6 个——中心孔 2 口边面语义按实测：圆柱面计数=6）；⑥(cylinder,+Z) 与 (cylinder,−Z) 对同一轴向圆柱面结果相等（无向匹配）；⑦(cylinder,+X) 对轴向 Z 的圆柱面 → no-match；⑧plane 省略 axis（None/空串两种输入）→ ValidationError；⑨"" 与 None 规范化后行为完全一致（同构断言）；⑩两个等面积平面的字典序平局（构造错位双块）按 (x,y,z) 选小；EdgeSelector：parent 不匹配/曲线过滤空集 → TopologyReferenceError（消息含命令 id 与描述子 JSON）；tessellation 弦差减半片数单调增多且顶点全部落在 bbox 内；GeomVersionError monkeypatch 测试。
  - `tests/test_layering.py`（结构性守卫，AST 扫描，唯一判定规则）：**`src/mycad/geom/` 包以外的任何 src 模块都不得 import `build123d`/`OCP`/`numpy`，唯一 src 白名单=`src/mycad/app.py`（组合根，允许 import geom+core，不允许直接 import build123d/OCP/numpy——它只经 geom 公开面接线）；geom 包内模块数量与拆分不限（kernel.py/selectors.py/_b123_ops.py/io 等均可）；tests 中仅 `tests/geom/` 与 `tests/helpers/step_roundtrip.py`（T8 新增的测试专用 STEP 读回辅助）可直接 import 这三者**。core/commands/cli/agent/formats/plugins 出现即 fail。T5/T8 新增 geom 内模块时本测试无需改允许列表。
  -   Must NOT do：不实现 extrude/revolve/hole/hole_pattern/fillet/boolean_cut（T5）；不做 STEP/STL（T8，Protocol 仅占位）；不静默吞异常；不引第二个 OCCT 绑定；不在 DTO 中泄漏 OCCT/numpy 类型；tessellation 不落任何文件格式、不碰 OpenGL。
  Parallelization: Wave 1 | Blocked by: T1 | Blocks: T5, T8 | 与 T3, T4 并行
  References:
  - `/tmp/opencode/mycad-spike/flange_spike.py:14-47`（BuildPart/Cylinder/Mode.SUBTRACT/GeomType.CYLINDER/bbox/volume 断言）；`/tmp/opencode/mycad-spike/fillet_probe.py`（**已实测锁定的签名证据**：`Cylinder(10,20,mode=Mode.SUBTRACT)` 体积=π·8·(40²−10²)=37699.111843 解析一致；`Box(5,5,30,mode=Mode.SUBTRACT)` 从 20³ 切出体积 3750 解析一致——box/cylinder 三模式无需再探索）；尖刺体积打印值 36794.3332mm³ 是 4 位舍入显示，解析真值 36794.333158843656…（见 T11 golden 纪律）
  - ledger E1（export_step/import_step/export_stl/filter_by/group_by/sort_by 习语）、E4（FreeCAD 官方四路径：语义选择+建模即代码+datum；失效须显式报错；V2 命名算法仍 draft——不赌拓扑命名）、A1/A6、R2/R3/R14/R15
  - `docs/技术路线.md:55-63`（geom 职责：适配/网格化/导入导出）、`docs/需求分析书.md:80-88`（F-MOD-01）
  - build123d 0.11.1 已装于本机 venv（尖刺目录）；执行代理必须用 `uv run python` REPL/inspect 自查实际 API 签名，禁止凭记忆写选择器 API
  Acceptance criteria:
  - `uv run pytest tests/geom tests/test_layering.py -q` 全绿；`uv run basedpyright` 零错误；AST 守卫测试通过。
  - 三个解析体积：box 80×80×8=51200（#round11-1：测试内按 `80*80*8` 公式直算，禁止手写结果）；cylinder r40 h8=40212.385965…；尖刺法兰 cut 形 36794.3331588437…（测试内用 `math.pi*8*(40**2-10**2-4*3**2)` 直算，容差 1e-6 mm³；禁止手写 36794.3332）全部断言通过。
  QA scenarios:
  - happy：`uv run pytest tests/geom tests/test_layering.py -q` 全绿；体积表与 tessellation 片数单调性输出存 `.omo/evidence/task-2-phase0-mvp.md`。
  - failure：rank=99 选择器必须抛 TopologyReferenceError（专用测试）；**版本门 QA 必须打在唯一版本源上**：`monkeypatch.setattr("importlib.metadata.version", lambda _n: "9.9.9")` 后用 `importlib.reload(mycad.geom.kernel)`（或把模块级版本检查抽成 `_assert_b123d_version()` 在测试中直接调用）必须抛 GeomVersionError 且消息含 9.9.9 与 (0,11,1)；再加 `monkeypatch` 返回 `"0.11"`（不可解析为三段）分支；**禁止 monkeypatch `build123d.__version__`**（实现不读该属性，打了也触发不了门，测试会假绿）；在 core/ 临时加一行 `from build123d import Cylinder` → test_layering 必须红，还原后绿（输出附证据）。
  Commit: Y | `feat(geom): sealed build123d kernel adapter with predicate selectors and neutral DTOs`

- [x] 3. T3 命令框架：CommandSpec/JSON Schema 子集校验/注册表/CLI 语法双向映射
  What to do / Must NOT do:
  - `src/mycad/commands/spec.py`：`@dataclass(frozen=True) CommandSpec(id: str, version: int, summary_en: str, label_zh: str, params_schema: Mapping[str, object], cli: CliSyntax, undo_compensation: Literal["history_replay"] = "history_replay")`（#round11-NB1：字段顺序写死，带默认值的 undo_compensation 置末位）；`summary_en` 为 CLI help/`commands` 输出消费的英文摘要；`label_zh` 为阶段 1 UI 左栏预留的中文标签（**阶段 0 仅作为数据存在，无任何代码消费它，但必须随 8 条命令全部填好**）；**`undo_compensation` 字段唯一允许值为字符串字面量 `"history_replay"`（默认值即此，构造时传任何其他值 ValidationError）**——这是对 `docs/技术路线.md:157`"撤销补偿信息"基线要求的显式满足：字段仍存在且每条命令声明，但阶段 0 语义统一为历史重放，不做 per-command 反向操作（ADR-001 引用此字段说明决策，**这是协议遵从不是偏离**）；`CliSyntax(verb_aliases: tuple[str,...], positional: tuple[str,...]=())`。id 命名空间逐字对齐 UI 初稿 §5.3（feature.*/modify.*）。
  - `src/mycad/commands/validation.py`：`validate_params(spec, params, defs: Mapping[str, object] | None = None) -> dict[str, object]` 自实现 JSON Schema **固定子集（完整关键字清单即下列集合，附录 A 用到的每一个都在其中；遇到清单外关键字必须报错而非忽略，防止 schema 静默失真）**：
    1. `"type"`：integer/number/string/boolean/array/object（integer 拒绝 bool）；2. `"properties"`+`"required"`（object）；3. `"additionalProperties": false`（未声明键 ValidationError，消息含点路径）；4. `"items"`（array，单一 schema，数组每元素校验）；5. `"minItems"`/`"maxItems"`；6. `"minimum"`/`"maximum"`/`"exclusiveMinimum"`/`"exclusiveMaximum"`；7. `"minLength"`/`"maxLength"`；8. `"enum"`；9. **`"const"`**（值精确相等，Python `==`，number 按精确值）；10. `"default"`（缺键填充，不覆盖显式 null：null 对非空类型 ValidationError）；11. **`"oneOf"`**（子 schema 数组：恰好 1 个分支整体校验通过；0 个或 ≥2 个通过均 ValidationError，错误消息列出各分支首错）；12. **`"$defs"`+`"$ref"`**：只支持文档本地片段引用，形式固定为 `"$ref": "#/$defs/<Name>"`；解析规则=校验器维护**单一共享定义表**（`validate_params(spec, params, defs: Mapping[str, object] | None = None)`，defs 由调用方注入，本 todo 不自建正式表文件）：正式常量表在 **T7 创建的 `src/mycad/builtin_commands/defs.py`（唯一路径，符号 `COMMAND_SCHEMA_DEFS`，#round9-7）**——T3 在 Wave 1 先于 T7，其 `$ref` 单测使用**测试内内联最小 defs fixture**（至少 Mode/Center3/Positive），不得 import 尚不存在的 builtin_commands.defs，也不得在 commands 包内放置第二份正式表；T7 落地后各命令 schema 的 `$ref` 一律解析到该文件的表（AST/路径断言：`COMMAND_SCHEMA_DEFS =` 赋值在 `src/` 仅 `src/mycad/builtin_commands/defs.py` 一处，T7 验收）；T7 把附录 A.0 的 FaceSelector/EdgeSelector/Position/Depth/Pattern/Profile/Mode/Center3/Positive/Tool/Hole 作为该常量表内容与 8 条命令 schema 同模块落地，各命令 schema 中的 `$ref` 一律解析到该表（`$defs` 也允许出现在单条命令 schema 内并就近遮蔽同名定义，但阶段 0 8 条命令不使用此形式）；**feature.hole 的 params_schema 是根级 `{"$ref": "#/$defs/Hole"}`（#round11-3：根级 $ref 属合法引用形式，校验器必须支持 params_schema 整个就是 $ref 的情况，键序取被引 def 的 properties 声明顺序）**；任何指向表外名字或非 `#/$defs/` 前缀的 `$ref` 在校验器单测中必须失败；13. `"description"` 仅文档用途、不参与校验。
    长度 mm/角度 deg 约定在 schema description 声明；类型收窄后返回精确类型 dict；错误抛 `core.exceptions.ValidationError`，消息含字段点路径（`holes.2.radius`）与期望约束；纯函数零 IO。**8 条命令的字段级 schema 以本计划文末"附录 A：Command schema catalog（规范）"为唯一权威，T7 逐字落地，执行者不得自行发明字段；附录与本关键字清单不一致时以本清单能力为准并回改附录。**
  - `src/mycad/commands/registry.py`：`CommandRegistry`（register/get/list_by_category/search(keyword)；**#round11-2 defs 唯一注入点：构造签名 `CommandRegistry(schema_defs: Mapping[str, object] | None = None)`，registry 持有 `schema_defs` 属性——T7 build_app 以 T7 定义的 `COMMAND_SCHEMA_DEFS` 注入，T3 单测以内联最小 defs fixture 注入；bus.execute/_execute_one/execute_batch、Document.replace_command_params、open_document 自动重放、T10 run --json/validate 所有 validate_params 调用点一律传 `defs=registry.schema_defs`，全仓禁止第二条 defs 获取路径**；**分类规则写死（#round7-NB2）：CommandSpec 不新增 category 字段，category 由 id 第一段前缀派生（`".".split(id)[0]` 前再取点号前的域：feature.*/modify.* → 第二段前的 "feature"/"modify"，即以 id 第一个点号前段为 category：`feature.extrude`→"feature"、`modify.fillet`→"modify"、插件 `demo.ping`→"demo"）**；`list_by_category()` 返回 `dict[str, list[CommandSpec]]` 按 category 分组、组内按 id 排序，测试断言 feature 类恰好 6 条（box/cylinder/extrude/revolve/hole/hole_pattern）、modify 类 2 条（fillet/boolean_cut）；重复注册同 id 不同 version 策略=同版本冲突抛 CommandConflictError，不同 version 共存并以 latest 为默认——阶段 0 内置命令只有 version=1，版本共存机制仅测 API 不启用多版本）；模块级默认单例由 core 注入（不搞全局隐式状态：Document/Bus 通过构造函数接收 registry，Document 构造即持有 registry 供 replace_command_params 取 spec 与 schema_defs，T7 new_document/open_document 负责注入同一 registry 实例）。
  - **`normalize_params(params: Mapping[str, object]) -> dict[str, object]`（与 validation.py 同模块，T3 是唯一 owner；schema 校验通过后、构造任何 dataclass/执行前调用，T2 geom 与 T6 加载层只消费已规范化的 dict，不得自行规范化）**：递归遍历 params 中所有谓词描述子对象，规则写死。**规范化后的内存表示与 wire 表示统一为单一形态=键省略（绝不产生 None 值、绝不写 null），保证 validate→normalize→validate 严格幂等（#round9-3）**：①任何 FaceSelector 形态对象（含 hole.target_face、hole_pattern.base_hole.target_face、fillet.edges[].parent_faces[] 等全部嵌套位置）的 `axis` 键：值为 `""`（空串）时，当且仅当同对象 `surface == "cylinder"` 才**删除该键**（不是替换成 None）；`surface == "plane"` 时空串在校验层已拒（plane 分支 enum 不含空串），规范化器再遇空串属防御性 ValidationError；②**EdgeSelector 的 `curve` 键适用同一规则**：值为 `""` 时删除该键（curve 可缺省=None，wire 省略键）；③键本来就不存在不补；④除上述两类空串删键外不做任何其他值变换（不做大小写/单位/别名转换，不把任何键的值改成 None）。消费侧一律用 `selector.get("axis") is None`/`edge_sel.get("curve") is None` 判定；dataclass 构造时缺键即默认 None。函数纯函数、无 IO。
  - `src/mycad/commands/grammar.py`：`parse_line(text: str, registry: CommandRegistry) -> tuple[str, dict[str, object]]`（**registry 必注入**：动词→命令 id 的解析依赖各 CommandSpec 的 cli.verb_aliases，无 registry 不可调用；执行者禁止用模块级动词表）与 `to_cli(command_id: str, params: Mapping[str, object], registry: CommandRegistry) -> str` 互逆（id→动词取该 spec 的 verb_aliases[0]）；**键序=spec.params_schema 的 `properties` 声明顺序（嵌套递归同规则，#round9-NB-C；根级 `$ref` 的 schema 键序=被引 def 的 properties 声明顺序，#round11-3），to_cli 是该规则的实现处，T7/T10/T11 的快照只引用不再定义**；**to_cli 输入与值域规则唯一权威（#round11-5）**：输入=经 `validate_params`（含 default 填充）+ `normalize_params`（删空串/None 键）之后的 params，**输出其全部键——含 default 填充键**（cylinder 的 center=[0,0,0]、mode=new 等一律显式出现；省略默认值的"精简输出"形式不存在，全仓唯一形态）；None 值键已被 normalize 删除故绝不出现在输出；**数字 canonical 形式**：整数取值的 float 序列化为无小数点整数形式（`0.0→0`、`25.0→25`），其余按 repr 最短往返——examples/flange_script.txt 与 T11 历史文本快照共用本规则，二者逐行一致由此闭合；语法=ASCII 英文 `verb key=value ...`；注释 `#` 与空行在脚本模式跳过。**value 词法规则（#round9-1，逐字写死，执行者不得发明第四种形态）**：①整数 `-?[0-9]+`、浮点（含小数点/科学计数法）；②布尔 `true`/`false`；③**双引号字符串**（`"`…`"`，反斜杠转义 `\"`/`\\`，用于含空格或特殊字符值）；④**裸标识符/枚举 token（新增正式规则，非权宜）**：正则 `[A-Za-z_][A-Za-z0-9_.+-]*`，可含一个前导符号（仅允许 `+`/`-` 各至多一个且必须在最前），用于所有枚举/判别值与带符号轴名：`new`/`add`/`cut`、`plane`/`cylinder`、`+Z`/`-Z`/`+X`、`circle`、`through_all`、`blind`、`center`、`polar` 等一律不加引号；切分以空白为界，`=`/`.` 不作为 token 边界（`target_face.axis=+Z` 中键在第一个 `=` 处分，值 `+Z` 整体成词）；裸 token 与数字/布尔形态冲突时按 ①② 优先（`true` 是布尔不是字符串）；裸 token 解析后作为字符串值进入校验，是否合法由 enum/oneOf 决定（非法枚举→语义层 ValidationError，不是词法错）；需要空格/`#`/`=` 等字符的值必须用双引号字符串。
  - **解析三层错误归类（写死，异常类型与 CLI 退出码一一对应，#4）**：
    1. **词法/批结构层**（动词都还没辨认出来）：引号未闭、裸 `=`、token 无法按 `key=value` 切分、标量数组括号未闭、非法转义、`begin-batch`/`end-batch` 结构错（见 T10 批矩阵）→ `CliSyntaxError(token_or_position, suggestion)`（suggestion 用 SequenceMatcher 取最接近的已注册动词别名）；
    2. **动词解析层**：词法合法但第一个 token 不是任何已注册命令的动词别名（含 `cylnder` 这类拼写近似）→ registry 查无后抛 **`UnknownCommandError(identifier=verb)`**（identifier 参数语义见 T1 异常清单第 14 项；消息含最接近建议；未知建模命令在 CLI 归运行错误退出码 1，区别于 CliSyntaxError 的用法错误 2——拼错动词属"要执行的建模命令不存在"，计划语义见 T10）；
    3. **参数语义层**：动词解析成功后，未知键/类型错/越界/oneOf 判别失败等一律经 T3 校验器抛 **`ValidationError`**（点路径消息）。
    三层在 grammar 单测中各至少 2 例并断言异常类型互斥（禁止把未知键抛成 CliSyntaxError、禁止把引号未闭抛成 UnknownCommandError）。
  - **嵌套文法（写死，二义性零空间）**：对象用扁平点键 `key.sub=v`；数组元素用扁平索引点键 `key.0.sub=v`（与校验错误点路径 `holes.2.radius` 同构）；方括号**仅**用于标量数组 `center=[0,0,0]`，不用于对象数组。必须在 grammar docstring 给出至少 6 条完整示例并各配 parse→to_cli→parse 往返测试，含：①`cylinder radius=40 height=8 mode=new`；②`hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 position.kind=center diameter=20 depth.kind=through_all`；③`fillet edges.0.parent_faces.0.surface=cylinder edges.0.curve=circle radius=2`；④`hole-pattern base_hole.target_face.surface=plane base_hole.target_face.axis=+Z base_hole.target_face.rank=0 base_hole.position.kind=center base_hole.diameter=6 base_hole.depth.kind=through_all pattern.kind=polar pattern.radius=25 pattern.count=4 pattern.start_angle_deg=0`；⑤`extrude profile.type=circle profile.radius=30 distance=10`；⑥`box size_x=10 size_y=10 size_z=10 center=[1,2,3]`。布尔模式只作键值 `mode=new|add|cut`；**None 值序列化规则（#round8-NB1，与 wire 省略键一致）**：to_cli 对值为 None 的可选键（axis/curve）一律省略不输出，parse_line 缺键即 None；`history --json → to_cli → parse_line` 加 None 往返用例（cylinder 选择器无 axis、EdgeSelector 无 curve 各一）；**动词 `cut` 唯一映射 modify.boolean_cut**，feature 命令的减法一律 `mode=cut` 键值（如 `cylinder ... mode=cut`），二者不得混用。
  - 本 todo 注册 **1 条示范命令 feature.cylinder**（schema 严格按附录 A：radius/height positive numbers、center x/y/z numbers default 0、mode enum new/add/cut default new；`summary_en="Create a cylinder"`、`label_zh="圆柱体"`、`undo_compensation="history_replay"`），与 COMMAND_SCHEMA_DEFS 雏形（至少含 Mode/Center3/Positive 三个 $def 并演示 $ref 解析），其余 7 条在 T7；测试覆盖该命令的框架全链路。
  - Must NOT do：不引 pydantic/jsonschema 第三方库（仅标准库）；不依赖 geom；不在本 todo 写几何语义；不做中文 CLI 语法（A10：CLI 英文，UI 才中文）；不让 registry 成为模块级可变全局；**不创建 `schema_tools.py`/任何 tool-schema 生成代码与 `tests/snapshots/`（面向 Agent 的工具 schema 是阶段 2 产品，仅以文字存在于 ADR-004 与附录 A）**。
  Parallelization: Wave 1 | Blocked by: T1（异常清单）| Blocks: T6, T7, T9 | 与 T2, T4 并行
  References:
  - `docs/技术路线.md:155-160`（§7 命令与 Agent 协议基线：稳定 id、JSON 参数、CLI 语法、执行前校验器、禁止无沙箱任意 Python）
  - `docs/UI设计初稿.md:146-205`（§5.3 命令 ID 与优先级；feature.cylinder 等逐字照抄）
  - `docs/需求分析书.md:101-110`（F-AGT-01/02/05：可读计划、确认、CLI 等价形式）、NF-03 可审计
  - ledger A6（谓词参数是 schema 中的对象描述子而非索引）、R9；工具 schema 未来形态只看本计划**附录 A**与 ADR-004，不写代码
  Acceptance criteria:
  - `uv run pytest tests/commands -q` 全绿：schema 校验（合法/类型错/越界/缺必填/默认填充/枚举错/const 不匹配/additionalProperties 未知键/items 数组元素类型错/minItems·maxItems 越界/**oneOf 判别：合法分支各 1、未知判别值、零分支/多分支**/**$ref 解析：本 todo 用测试内内联最小 defs fixture（#round9-7，禁止 import T7 的 builtin_commands.defs 或自建正式表文件）**：FaceSelector/Position/Depth 各 1 个合法例、坏 `$ref` 前缀与表外名字各 1 个失败例、清单外关键字（如 "patternProperties"）出现即报错例，断言错误消息含字段路径；**FaceSelector oneOf 分支纪律（schema 层前置校验，五例）**：①`{surface:"plane",axis:"+Z"}` 合法；②`{surface:"plane"}` 缺 axis → ValidationError；③`{surface:"plane",axis:""}` 空串 → ValidationError（plane 分支 enum 不含空串）；④`{surface:"cylinder"}` 与 `{surface:"cylinder",axis:""}` 均合法（同一对象不得同时匹配两分支——校验器断言分支命中数恰好 1）；⑤`{surface:"plane",axis:"Z"}` 无符号非法值 → ValidationError）；**normalize_params 测试（规范化是 T2 消费前置，必须在本 todo 锁定；#round9-3 全部按"删键"语义）**：①cylinder+axis="" 规范化后该键**不存在**（`"axis" not in d`），三个嵌套位置（hole.target_face、hole_pattern.base_hole.target_face、fillet.edges[].parent_faces[]）各 1 例；②EdgeSelector curve="" 规范化后键不存在、缺 curve 键时保持无键，各 1 例；③plane+axis="" 规范化器防御性 ValidationError；④**幂等闭环**：含 axis=""/curve="" 的 params 经 validate→normalize→**再 validate** 必须通过且结果与 normalize 后逐键相等（因规范化产物只有缺键形态，二次校验命中"可缺省"分支）；normalize 跑两次结果相同；⑤wire 篡改例：存档/计划 JSON 中显式 `"axis": null` 或 `"curve": null` 在 validate 阶段即 ValidationError（enum 不含 null、分支不接受 null）；⑥未提供 axis/curve 的其他键不被改动（深比较），且规范化产物中任何位置都不出现值为 None 的 axis/curve 键；undo_compensation 缺省="history_replay"、传非法值 ValidationError 各 1 例；grammar 往返性质测试 `parse_line(to_cli(id, p, registry), registry) == (id, p)` 对 20 组随机/固定参数（registry 为含 8 命令的 T7 装配结果或本 todo 示范注册表）；**裸标识符词法测试（#round9-1，逐例锁定）**：①`mode=new`/`surface=plane`/`axis=+Z`/`axis=-Z`/`depth.kind=through_all`/`profile.type=circle` 各解析为对应字符串值（非数字、非 bool）；②裸值非法枚举（如 `mode=banana`）→语义层 ValidationError 而非词法错；③含空格值必须加引号（`label="a b"` 成功，`label=a b` 词法失败 CliSyntaxError）；④裸 token 与数字/布尔形态区分（`flag=true`→bool、`n=3`→int、`s=true` 按 schema 字符串列枚举时为 str，由 schema 决定）；⑤裸 token parse→to_cli→parse 往返保持原字面量（`+Z` 往返不丢前导 `+`）；三层错误各至少 2 例（词法：引号未闭/裸=；动词：`cylnder`/`bogus`→UnknownCommandError；语义：未知键/负半径→ValidationError），断言异常类型不互混；**registry search 语义（#round9-8，逐字写死）**：搜索域=对每条 spec 匹配 `id` 与全部 `cli.verb_aliases` 与 `summary_en`（**不搜 label_zh**：阶段 0 CLI 英文；label_zh 留给阶段 1 UI 搜索）；匹配规则=大小写不敏感子串；返回 list[CommandSpec]，排序按 id 字典序；至少 3 个锁定测试：a) 按 id 子串命中（`search("cyl")` 含 feature.cylinder）；b) 按动词别名/summary 命中（`search("cylinder")` 经别名、`search("Create")` 经 summary_en）；c) 无命中返回 `[]`（非 None、不抛错）；list_by_category 与冲突同段；feature.cylinder 的 spec 与附录 A **逐字段相等**的断言测试（schema dict 静态比对，期望值手写于测试中，禁止反录）。
  - basedpyright 零错误；ruff 零告警；`tests/snapshots/` 不存在。
  QA scenarios:
  - happy：`uv run pytest tests/commands -q` 全绿；在 REPL 式一次性脚本 `uv run python -c` 中走 register cylinder → parse `cylinder radius=40 height=8` → validate → 断言 dict，输出存 `.omo/evidence/task-3-phase0-mvp.md`。
  - failure：`cylinder radius=-1 height=8` → ValidationError（exclusiveMinimum 0）；`cylnder radius=4 height=8` → UnknownCommandError 且建议含 `cylinder`（动词解析层，CLI 退出码 1）；`cylinder radius=abc height=8` → CliSyntaxError 指向 token（词法层，CLI 退出码 2）；`cylinder radius=1 height=2 extra=1` → ValidationError（未知键语义层）；四类必须有专用测试且异常类型互斥。
  Commit: Y | `feat(commands): command spec, schema validation, registry, bidirectional CLI grammar`

- [x] 4. T4 架构决策记录 ADR-001…006（+ 偏离基线说明）
  What to do / Must NOT do:
  - 新建 `docs/adr/`，六份 MADR 精简格式（# 标题 / Status: Accepted 2026-09-17 / Context / Decision / Consequences / References），全部中文：
    - **ADR-001 命令总线与历史重放**：唯一写入路径；undo=删命令+全量重放（不做 inverse、不做 brep 缓存，R17 记录演进口）；批事务=执行前快照、任一命令失败整体回滚；重放遇 TopologyReferenceError 必须显式报出命令 id（FreeCAD E4 教训）；坐标单位约定；**对技术路线 §7"撤销补偿信息"基线的遵从方式**：CommandSpec 保留 `undo_compensation` 字段且阶段 0 唯一取值 `"history_replay"`（协议字段显式存在，语义统一为重放，非删除、非偏离）。本 ADR 同时记录**基线偏离 ②**（headless 投影，含两项基线明列的阶段 0 交付物的后置）：①需求 §8.2 的 Chat 计划确认在阶段 0 投影为 CLI/JSON Plan + `confirmed_by` 审计字段（形态投影，确认红线不降级）；②需求分析书 §7 阶段 0 交付物明列"简单预览"（`docs/需求分析书.md:157`）、技术路线阶段 0 明列"简单 3D 预览"（`docs/技术路线.md:104`），本计划阶段 0 只交付 tessellation 内存数据接口（T2），预览本体后置到阶段 1 PySide6 壳。两项同属"headless 边界"这一个偏离主题，合并记录于本 ADR 的一个 `## 基线偏离` 段落。
    - **ADR-002 存档格式 v1**：JSON（schema：`{"format":"mycad.document","version":1,"metadata":{...},"commands":[{...}],"named_groups":[{"name","faces":[...],"edges":[...]}]}`——named_groups 元素恰好 name/faces/edges 三键，faces/edges 为附录 A.0 谓词描述子 JSON，CAE NamedGroup 是文档注释态：不进重放序列；命令元素含审计六字段 `id/version/params/ordinal/timestamp_utc/confirmed_by`（`ordinal` 为 int 从 0 起、`timestamp_utc` 为 ISO8601 UTC 字符串、`confirmed_by` 可空）**外加可选数组 `amendments`**：初始无此键；每次经历史参数编辑 API 重放（见 T6）追加一条 `{"at":"<ISO8601 UTC>","actor":"<str>","from_params":{...},"reason":"<str>"}`，原 params 被替换为新值但修订留痕）；UTF-8、.mc.json 扩展名；open 时恢复全部审计字段（打开后重放与参数编辑重放都**不改写原 timestamp**），version 校验+`migrations.py` 钩子注册（v1 无迁移体）；**阶段 0 无任何导入型历史节点**（STEP 读仅测试路径，不进存档 schema；`document.import_step` 是阶段 1 演进口，本 ADR 在 Consequences 注明）；brep 快照缓存列为未来 v2 演进口（E6 FreeCAD .FCStd 对照）。
    - **ADR-003 扩展点与插件 API 版本**：entry-points 组 `mycad.commands`/`mycad.formats`（预留 `mycad.datum`/`mycad.inspect` 文字）；manifest 契约（id/version/api_version/permissions/homepage；`CURRENT_API_VERSION="1.0"`，主版本 1 兼容、其他跳过）；**manifest 定位算法（#round7-4 必须写明）**：不设第三个 entry 组——核心导入每个贡献 entry 的 `EntryPoint.module`，在模块属性中找固定名 `manifest`（零参 callable 的返回值/dict/PluginManifest 三形态，按 module memoize 只取一次，字段损坏=manifest-error，缺失=missing-manifest，主版本不符=incompatible-api）；多 entry 合并的一个 DiscoveredPlugin 以 `entrypoint: tuple[str,...]` 记录去重排序后的 `<group>:<module>:<attr>` 引用；api_version 不兼容=跳过该插件+warning 不影响启动；插件=全信任 Python（R9，不做沙箱；沙箱只约束未来 Agent 生成代码 NF-07）；headless 信号 pre_command/post_command/command_amended/document_saving/document_saved。**插件命令贡献契约（写死）**：`mycad.commands` entry 的 callable 返回 `list[CommandContribution]`，`CommandContribution(spec: CommandSpec, handler_factory: Callable[[], CommandHandler] | None)` 为唯一携带形式（不拆第二个 entry 组）；handler_factory 省略时核心以 BuiltinModelingHandler 兜底（适用声明式建模命令）；插件处理器须实现 core 的 CommandHandler Protocol（实例属性 command_id + handle(params, ctx)，工厂零参返回已绑定自身 id 的实例），经 api_version 主版本门控通过后才实例化；demo.ping 型非几何命令必须自带 handler。
    - **ADR-004 MCP 边界（只决策不实现）**：MyCAD 作 stdio MCP server；工具面=只读查询 + 计划面（list_commands/make_plan/validate_plan/query_document/export_dry_run）；状态用显式 plan_id 句柄（规范无协议级会话，E3）；`confirm_execute(plan_id, confirmation_token)` 的 token 只能由产品侧用户交互产生，任何远程客户端不可自造；落地时在 MCP Python SDK 锁主版本（v2 对齐 2026-07-28 规范，MCPServer；旧代码 pin <2，R16），优先用规范 elicitation（InputRequiredResult）承载确认；阶段 0 不引 mcp 依赖。**A19（国产 LLM 路径）显式处置**：阶段 2 选型限定 OpenAI 兼容抽象，云端候选 DeepSeek/通义、本地候选 Ollama(aarch64 可行)，不绑定境外 API；该选型是 accepted/future 假设，阶段 0 无任何 LLM/网络/API 调用代码，ADR 须出现 "A19" 字样以便审计核对。
    - **ADR-005 格式提供方分级**：FormatProvider 注册表对齐 OCCT 7.8 DE_Wrapper 的 name×vendor provider 模型（E10），另加 `priority` 整数（默认 100，同扩展名多 provider 取小值，priority 相同且扩展名重叠时注册抛 `ProviderConflictError(extension, provider1, provider2)`）；import 三级 DUMB_SOLID / ASSEMBLY_WITH_ATTRS / EDITABLE_FEATURES——**任何外部格式永远到不了第三级**；免费序列 STEP AP242/STL/BREP（阶段0：**STEP 只写产品化；STEP 读仅测试辅助路径用于往返断言，F-DOC-03 产品化导入在阶段 1**）→ IGES/glTF/OBJ → 3MF(lib3mf)/DXF(ezdxf)；商业墙 JT/Parasolid(x_t)/ACIS(sat)/sldprt/NX/CATIA 仅经外部持证插件（E5：ODA 会员制无席位费 vs CAD Exchanger 按席位季度计费，均不可随 Apache 核心再分发）；DWG 不碰（无免费合规写，R11）。
    - **ADR-006 平台分层**：T1 Ubuntu 22.04/24.04 x64 + Win10/11 x64（CI 三 job 全过，pip wheel 直装）；T2 麒麟 V10 SP1+（glibc 2.31+麒麟补丁）/UOS Server 20/麒麟 V11 on 鲲鹏·飞腾 aarch64（manylinux_2_31_aarch64 wheel 直装，实机/QEMU 回归在阶段 1）；基线声明 **glibc≥2.31**，UOS V20 桌面 D 版（2.28）为已知不支持（R13）；海光/兆芯=x86 同栈；T3 龙芯 LoongArch64 技术可行（CPython 3.12 原生 triplet；PyPI 官方拒收 wheel，discuss.python.org #105548；龙芯镜像 pypi.loongnix.cn 按 glibc 分源；须源构建 OCCT/OCP），阶段 1 末 spike 做 go/no-go；申威不纳入。本 ADR 同时记录**基线偏离 ①**：打包从技术路线 §9 设想的 conda 主路径改为 pip+uv（E1 官方 README 原文 "pip recommended for most users"；E11 本机实证；conda-forge build123d 滞后 0.9.1 仅留作离线备选）。
  - **对基线文档的显式偏离恰好两处**（附证据，逐条指定到唯一 ADR 文件；不得把基线自身的阶段分期伪报为偏离）：**偏离 ①**（记录于 **ADR-006**）：打包从技术路线 §9 设想的 conda 主路径改为 pip+uv（E1/E11，官方 README 原文 "pip recommended for most users"）；**偏离 ②（headless 投影，一个偏离主题、两个后置项，记录于 ADR-001 的一个 `## 基线偏离` 段落）**：a) 需求 §8.2 的 Chat 计划确认在阶段 0 投影为 CLI/JSON Plan + `confirmed_by` 审计字段（形态投影，确认红线不降级）；b) 基线两份文档明确列为阶段 0 交付物的"简单预览/简单 3D 预览"（`docs/需求分析书.md:157`、`docs/技术路线.md:104`）后置到阶段 1，阶段 0 只交付 tessellation 数据接口。**#round11-NB5：预览后置与 Chat 计划确认投影同属偏离②"headless 交付"这一条基线偏离的组成项，不是独立第三条偏离——ADR-001 的 `## 基线偏离` 标题计数恒为 2（ADR-001/ADR-006），F2/T4 标题计数测试不变。**Scope 延期登记表 F-MOD-02 行已同步注明。**协议增强（增强不冲突，明确不是偏离，不得计入 ADR 偏离计数）**：每条命令增加 `version` 字段（支撑未来同 id 多版本共存）；保留 `undo_compensation="history_replay"` 字段以满足技术路线 §7 的撤销补偿信息要求。
  - ADR 中"基线偏离"必须以固定标记段落出现（每份 ADR 最多一处，标题逐字写作 `## 基线偏离`；两处偏离各只在 ADR-001/ADR-006 出现一次；无偏离的 ADR 不得出现该标题），供验收脚本精确计数。
  - Must NOT do：不修改 docs/ 三份基线原文；ADR 不写实现代码片段以外的产品代码；不承诺商业格式时间表；不把 MCP/PLM/CAE 写成阶段 0 实现。
  Parallelization: Wave 1（纯文档，可最早并行）| Blocked by: T1（docs/adr 目录与提交规范）| Blocks: 无（T6/T8/T9 以 ADR 为约束，可先读草稿）| 与 T2, T3 并行
  References:
  - ledger §4 A13–A20、§5 E2/E3/E5/E6/E9/E10、§6 R9/R11/R13/R15/R16/R17
  - `docs/技术路线.md:30-38`（五架构原则：单一写入路径、多入口同源、计划执行分离、Document 真相源、注册式扩展）、`:176-180`（开源合规）
  - `docs/需求分析书.md:136-149`（确认流产品规则）、NF-02/NF-07
  - MADR 格式：https://adr.github.io/madr/（精简子集即可，无需联网，按上述六字段）
  Acceptance criteria:
  - **脚本化验收（零人工自查）**：`tests/test_adr_docs.py` 用 pathlib+正则断言：`docs/adr/` 恰好 6 份 `ADR-00N-*.md`；每份含 `Status`/`Context`/`Decision`/`Consequences`/`References` 五个节标题；关键字命中——ADR-001 含 "重放" 与 `history_replay`、ADR-002 含 `timestamp_utc` 与 `amendments` 与 `named_groups` 且**不含** `imported_solid`、ADR-003 含 "api_version" 与 "CommandContribution" 与 "EntryPoint.module" 与 "missing-manifest" 与 "incompatible-api"、ADR-004 含 `confirm_execute` 与 `plan_id` 与 `A19`、ADR-005 含 `DE_Wrapper` 与三级枚举三个标识符与 "DWG" 与 `priority` 与 `ProviderConflictError`、ADR-006 含 "glibc" 与 "2.31" 与 "LoongArch" 与 "manylinux_2_31"；**偏离计数：逐字标题 `## 基线偏离` 在六份 ADR 中恰好出现 2 次，且分别位于 ADR-001 与 ADR-006 文件内（文件名断言，不靠内容猜测）**。
  - markdown lint 不做硬性要求；ADR 间引用编号正确由测试间接覆盖。
  QA scenarios:
  - happy：`uv run pytest tests/test_adr_docs.py -q` 绿；测试输出的每份 ADR Decision 一句话摘要存 `.omo/evidence/task-4-phase0-mvp.md`。
  - failure（用**精确短语白名单**而非模糊禁止词，避免误伤"阶段 0 不实现 X"这类合理表述）：测试维护一份"超前实现短语"精确清单（如 `阶段 0 实现 MCP server`、`阶段 0 实现 PySide6`、`阶段 0 接入真实 LLM`、`阶段 0 实现 DWG 写入`），逐字子串命中任一即红；另在临时 ADR 删掉 Status 节、或在 ADR-003 加第三个 `## 基线偏离` 标题，三种篡改分别验证测试变红；自查结果写入证据后还原。
  Commit: Y | `docs(adr): record phase-0 architecture decisions 001-006`

- [x] 5. T5 geom 特征层：参数化截面 + extrude/revolve + hole/极阵列孔 + fillet
  What to do / Must NOT do:
  - 在 geom 包新增 `profiles.py`：参数化截面描述子（frozen dataclass，标准库类型）——`Profile` 抽象 + `CircleProfile(radius, center=(x,y))`、`RectProfile(width, height, center=(x,y))`（阶段 0 只这两种，够法兰与基础拉伸件）；截面位于工作平面（默认 XY，z=0；支持绕 X/Y 旋转的 datum 平面描述仅留字段不实现）。
  - 扩展 `BuildKernel.apply` 支持：`feature.extrude`（profile + distance 双向符号 + mode new/add/cut）、`feature.revolve`（profile + axis 枚举 X/Y 或过原点方向向量 + angle_deg，默认 360）、`feature.hole`（**以几何谓词定位**：target_face: FaceSelector + position 描述子（`{"kind":"center"}` 为面心；阶段 0 只支持 center，其余定位留 schema 拒绝而非静默，不允许裸拓扑索引）+ diameter + depth（`{"kind":"through_all"}` 或 `{"kind":"blind","value":...}`）；**target_face 必须解析为平面**：解析结果非平面（如选到圆柱面）固定抛 TopologyReferenceError（reason="target-not-plane"，descriptor 回显），不尝试曲面定位；position=center 仅对平面有定义；**钻孔方向（写死）**：孔轴=定位面在面心处的**外法向**；blind 沿外法向反方向（向材料内部）延伸 value 长度；through_all 沿该轴双向包围盒穿透整个实体（等价 build123d 以该面外法向为轴的贯通孔，尖刺法兰路径已实证））、`feature.hole_pattern`（base_hole 经 `{"$ref": "#/$defs/Hole"}` 共享 Hole 定义（#round12d-1：与 A.0/A.1/T7 同一机制，禁止内联同构表述；含自己的 target_face 谓词）+ pattern: `{"kind":"polar","radius","count","start_angle_deg"}`——阶段 0 只实现 polar；`kind=linear` 由校验层以明确错误拒绝（未实现，不是静默接受）；**极阵列局部坐标系（#round7-3，二选一方案中采用"阶段 0 限制"方案，执行者零发明权）**：阶段 0 仅接受 `base_hole.target_face.surface=="plane"` 且 axis 为 `"+Z"`/`"-Z"` 的水平面——①schema 层不拒（+X 等平面对 feature.hole 仍合法），在 geom 执行 hole_pattern 时校验解析平面的外法向与全局 Z 平行（|n·ẑ| ≥ 1−1e-9），不满足固定抛 `TopologyReferenceError(reason="pattern-target-not-horizontal", descriptor_json=...)`；②角度参考系因此就是全局 XY 平面：第 i 个孔心相对基面面心位于 `(R·cos(θ0+2πi/count), R·sin(...))`（全局坐标），`start_angle_deg=0` ⇔ 全局 +X，正向=从 +X 朝 +Y（自 +Z 俯视逆时针），对 +Z/−Z 目标面使用同一套全局 XY 角度定义（−Z 面不做镜像翻转）；③每个实例孔的钻孔方向仍按 feature.hole 规则跟随该定位面外法向；④一般斜面上的投影局部系（局部 X=+X 在面内投影、退化时用 +Y）在 ADR-001/005 记为阶段 1 演进口，阶段 0 不实现；测试：+Z/−Z 面各一例孔心坐标解析断言、`+X` 竖直面 base_hole 执行 hole_pattern→pattern-target-not-horizontal、start_angle_deg=90 首孔落在 +Y、count=4 孔心集合与法兰 golden 一致））、`modify.fillet`（edges: EdgeSelector 数组 + radius）、`modify.boolean_cut`（tool 内联原型体 {type:box|cylinder,...}，唯一使用 `cut` 动词的命令）。
  - **法兰语义约束（验收牵引）**：法兰的中心孔与 4 个均布孔必须都能由 feature.hole / feature.hole_pattern 谓词路径完成（中心孔 target_face=最大 +Z 平面、position=center、through_all）；boolean_cut 不是法兰路径，只为通用差集能力存在，测试用 box 工具体。
  - 实现纪律：所有 OCCT 交互在 geom 包内（kernel.py 可调用同包 `_b123_ops.py` 等私有模块）；layering 守卫只按"geom 包外不得 import build123d/OCP/numpy"一条判定，geom 内拆模块无需改守卫；build123d 构造失败（零厚度/干涉/fillet 半径过大等 OCCT 异常）统一捕获包装为 T1 清单中的 `core.exceptions.GeometryBuildError(command_id, reason, occt_summary)`，禁止把 OCP 异常文本直接穿透边界（可带摘要字符串）；**不新增异常类**。
  - **fillet 调用签名已由规划师尖刺在 build123d 0.11.1 实测锁定（零探索留给执行者）**，证据 `/tmp/opencode/mycad-spike/fillet_probe.py`：方法式 `part.fillet(radius: float, edge_list: Iterable[Edge]) -> Solid | Part`（实测签名 `Part.fillet(self, radius, edge_list)`；**参数顺序是半径在前**，`part.fillet(edges, radius)` 实测抛 `TypeError: 'float' object is not iterable`，禁止使用）；边集合用 EdgeSelector 解析后得到的 build123d Edge 可迭代对象，典型解析习语 `part.edges().filter_by(GeomType.CIRCLE)`（实测法兰形返回 4 条圆边、`e.radius` 取值 {10.0,40.0}）或 parent_faces 谓词链；半径超过几何允许（实测边界场景）OCCT 抛错由统一包装成 GeometryBuildError。顶层函数式 `fillet(edge_list, radius)` 同样可用（参数顺序相反），**geom 内固定只用方法式一种**以消除二义性。
  - **revolve 轴归一化（写死，无判断空间）**：axis 为三元组时校验器在 schema 层只接受 3 个 number（见附录 A）；geom 层在构造前断言 `abs(norm(v)-1.0) <= 1e-9`，超差抛 ValidationError（消息含原始向量与实测 norm 值；**不做自动归一化、不 warning**——避免用户以为绕的是另一根轴）；方向向量取反视为合法（旋转角 360 时几何等价）；专用测试：合法单位轴 (1,0,0)/(0,1,0)、非单位轴 (1,1,0)（norm=√2）必须 ValidationError、(0,0,0) 必须 ValidationError。
  - 复用尖刺验证过的习语：PolarLocations + Cylinder(mode=SUBTRACT)（/tmp 尖刺 27-32 行）；fillet 与 box/cylinder 三模式见 `/tmp/opencode/mycad-spike/fillet_probe.py` 全部实测输出（引用即权威，执行者不得再改签名）。
  - 测试 `tests/geom/test_features.py`：extrude 圆截面（解析体积 πr²h）/方截面；revolve 矩形绕 Y=360 得空心/实心圆柱体积解析；hole through_all（谓词选最大 +Z 面、position=center）后体积=原体积−π(d/2)²·贯通长度；**尖刺法兰 5 孔全部经谓词路径**：cylinder r40 h8 → feature.hole 中心 φ20 through_all → feature.hole_pattern polar 4×φ6@R25，体积 36794.3331588437…（测试用 math 公式直算，容差 1e-6）、bbox.size=(80,80,8)、圆柱面 6；fillet 前后体积差与边数变化；boolean_cut 用 box 工具体切圆柱的解析体积；错误：孔定位谓词不匹配（TopologyReferenceError 含命令 id）、fillet 半径>几何允许（GeometryBuildError）、pattern.kind=linear 明确拒绝；**极阵列水平面限制（#round7-3）**：+Z/−Z 面各一例孔心坐标解析断言（start_angle_deg=0 首孔在 +X、=90 在 +Y，孔心相对基面面心）；在 +X 竖直面上执行 hole_pattern→TopologyReferenceError(reason="pattern-target-not-horizontal")；**blind 孔**：在 Box20³ 顶面 center 打 blind 孔（diameter=4,value=5），**唯一验证方法=mass_properties 体积断言**：体积减少量恰为 π·2²·5（贯通则会是 π·2²·20，体积值本身即区分盲/通，禁止用 STEP 读回或截面查询作为第二路径）；**target_face 选到圆柱面**（surface=cylinder）固定 TopologyReferenceError(reason="target-not-plane")；**盲孔反向语义**：在同一实体 −Z 面打同样盲孔，孔仍向材料内部（验证外法向反向时深度方向跟随）。
  - Must NOT do：不做自由草图/约束求解器（无 sketch.* 命令）；不实现 hole_pattern linear/chamfer/shell/mirror（P1/P2，阶段 0 注册表里不出现这些 id）；不引入 numpy DTO；不吞 OCCT 异常；不在命令层（commands 包）做几何计算。
  Parallelization: Wave 2（单波；T6 在 Wave 3，因批回滚/集成测试依赖本波的孔特征原语）| Blocked by: T2 | Blocks: T6, T7, T8, T11 | 并行：无
  References:
  - `/tmp/opencode/mycad-spike/flange_spike.py:27-47`（极阵列孔与断言）；`/tmp/opencode/mycad-spike/fillet_probe.py`（fillet 锁定签名实测：`Part.fillet(radius, edge_list)`；`part.edges().filter_by(GeomType.CIRCLE)` 圆边选择；半径 1.0 对 Box 10³ 顶边实测体积 991.7994）
  - ledger E1（build123d 习语清单）、E4（谓词定位四条抗脆弱路径）、A6、R3（TNP：少做强参数化编辑，谓词引用+golden 锁定）
  - `docs/UI设计初稿.md:160-185`（P0 命令 id：feature.extrude/revolve/hole/hole_pattern、modify.fillet/boolean_cut）
  - `docs/需求分析书.md:47-56`（首期 In）、技术路线.md:102-106（阶段 0 特征范围）
  Acceptance criteria:
  - `uv run pytest tests/geom -q` 全绿；新原语每条至少 3 个测试（解析体积/错误谓词/OCCT 失败包装）；**box/cylinder 的 mode=cut 在 T2 已交付并在 T5 测试中复用，但法兰序列的孔一律走 feature.hole/feature_hole_pattern 谓词路径**；法兰形特征序列（cylinder r40 h8 new → feature.hole 中心孔 φ20 through_all（最大 +Z 面 center 谓词）→ feature.hole_pattern polar 4×φ6@R25）经 kernel.apply 逐条执行后 volume 等于 math 公式真值 36794.3331588437（容差 1e-6）、bbox 80×80×8、圆柱面 6；序列中**不出现** `mode=cut` 的 cylinder，也不出现 modify.boolean_cut（专用断言扫描该序列命令 id 列表）。
  - basedpyright/ruff 零告警；layering 测试保持绿。
  QA scenarios:
  - happy：`uv run pytest tests/geom -q`；另跑一段内联脚本用 kernel.apply 复现尖刺法兰并打印 volume/bbox/圆柱面数，输出存 `.omo/evidence/task-5-phase0-mvp.md`。
  - failure：对同一几何连续两次 hole 定位谓词相同但面已变化的场景，断言得到显式 TopologyReferenceError/GeometryBuildError 而非静默选错面；fillet(radius=999) 必须 GeometryBuildError；两失败用例输出附证据。
  Commit: Y | `feat(geom): parametric profiles, extrude/revolve, predicate-located holes, polar pattern, fillet`

- [x] 6. T6 core：Document/CommandBus/重放 undo/批事务/信号/JSON 存档 v1/Plan 状态机
  What to do / Must NOT do:
  - `src/mycad/core/kernel_protocol.py`：`@runtime_checkable Kernel(Protocol)`——`reset()`、`apply(command_id: str, params: Mapping[str, object]) -> None`；**core 依赖倒置：只持有 Protocol，不 import geom**（接线在顶层 composition，T7/T10）。
  - **`src/mycad/core/handlers.py`（命令处理器契约，#7 缺失符号补齐；分派机制写死，禁止执行者另立）**：`@runtime_checkable CommandHandler(Protocol)`：`command_id: str`（**实例属性，非类属性**）+ `handle(params: Mapping[str, object], ctx: HandlerContext) -> object | None`；`HandlerContext` 为 frozen dataclass，**恰好两字段 `kernel: Kernel`（只读引用）与 `command_id: str`（当前正在执行的命令 id，由 Bus 逐调用注入）**；**返回值约定：建模处理器返回 `None`（经 kernel.apply 产生副作用），非几何命令（如插件 demo.ping）可返回任意可 JSON 序列化值**。
    - **分派唯一机制（写死）**：`BuiltinModelingHandler(command_id: str)` 构造时绑定单条命令 id（`self.command_id`），`handle` 内调 `ctx.kernel.apply(self.command_id, params)`、恒返回 None；T7 装配时为 8 条内置命令各构造一个绑定实例：`{cid: BuiltinModelingHandler(cid) for cid in BUILTIN_COMMAND_IDS}`。**禁止**让一个共享无状态实例"内部按 command_id 猜命令"（handle 不接收 id 时无法知道当前命令）；ctx.command_id 作为第二保险（Bus 必须传入与映射键一致的 id，断言二者相等）。插件工厂 `handler_factory()` 零参返回已绑定自身 command_id 的 handler 实例（demo 的 `DemoPingHandler()` 内 command_id="demo.ping"）。
    - Bus 执行时以 `handlers[id].handle(params, HandlerContext(kernel=kernel, command_id=id))` 的返回值作为 `execute()` 返回值（内置路径恒 None）；不引入全局 Result 包装类型。
  - **`src/mycad/core/ports.py`（第二倒置，为 T8 先于 T7 解环）**：定义三个 `@runtime_checkable` Protocol（core 只定义、不实现、不 import geom/formats）：
    - `ExportableKernel(Protocol)`：`reset() -> None`、`apply(command_id: str, params: Mapping[str, object]) -> None`、`mass_properties() -> MassProperties`、`export_step(path: Path) -> None`、`export_stl(path: Path) -> None`（方法名与 T2 BuildKernel 公开面逐字一致；**MassProperties/BoundingBox/Tessellation 三个中立 frozen DTO 已由 T1 在 `src/mycad/core/geometry_types.py` 唯一定义**（字段见 T1），ports.py 从同模块 import 类型；T6 只保留字段一致性消费，不新建、不重复定义，core 绝不 import geom）；
    - `FormatPort(Protocol)`：`name: str`、`vendor: str`、`priority: int`、`extensions: tuple[str, ...]`、`can_write: bool`，方法 `write(geometry: ExportableKernel, path: Path) -> None`（geometry 参数必须是 ExportableKernel，不得只写 Kernel——后者缺 mass_properties/export_* 方法，strict 下必报错）；
    - `FormatResolver(Protocol)`：`resolve(path: Path) -> FormatPort`。
    CommandBus/Document 不依赖这些端口，仅 T8/T10/未来 MCP 组合时使用。**BuildKernel 与 ExportableKernel 的结构一致性测试归 T6（波次约束：T2 在 Wave 1 不能 import Wave 3 的 T6 类型）**：T6 新增 `tests/core/test_ports.py`，import `mycad.geom` 的 BuildKernel 与 `mycad.core.ports` 的 ExportableKernel，断言 `isinstance(BuildKernel(), ExportableKernel)` 通过（runtime_checkable 验方法存在性，方法名集合逐字一致）+ basedpyright strict 下 `kernel: ExportableKernel = BuildKernel()` 赋值通过（`uv run basedpyright` 零错误覆盖）；**T2 不得包含任何对 ExportableKernel 的引用或测试**，T2 只按 line 155 的公开面签名实现。
  - `document.py`（**核心 DTO 在此唯一定义，全包只准从本模块 import，禁止第二处重复定义**）：
    - `ExecutedCommand` frozen dataclass **恰好六审计字段**：`id: str, version: int, params: dict[str, object], ordinal: int, timestamp_utc: str, confirmed_by: str | None`；外加可选修订留痕 `amendments: tuple[CommandAmendment, ...] = ()`（`CommandAmendment(at: str, actor: str, from_params: dict[str, object], reason: str)`；初始命令该元组为空，不计入"六字段"计数——存档中无修订时不出现 amendments 键）。
    - **`AffectedObject = Literal["box_body", "cylinder_body", "extruded_body", "revolved_body", "hole", "hole_pattern", "edge", "tool_body"]`**（模块级 Literal，八字面量与 B.2 逐字一致）；`PlannedCommand` frozen dataclass：`id: str, version: int, params: dict[str, object], summary_en: str, affected_object: AffectedObject`（**summary_en 唯一来源（#round8-4）：计划加载器/CLI 批构造在 registry.get(id) 命中后从 spec.summary_en 复制，禁止来自计划文件——B.1 step 恰好四键（id/version/params/affected_object），显式包含 summary_en 经 additionalProperties:false 拒绝；构造顺序=先查 registry（未知 id 此时即 UnknownCommandError，早于 summary 复制）→复制 summary_en→查 B.2 affected_object；测试：解析出的每条 PlannedCommand.summary_en == registry.get(id).summary_en、计划 step 多给 summary_en→ValidationError、未知 step id→UnknownCommandError**；**静态类型即锁定八字面量**：传表外字符串 basedpyright 报错；构造时另做运行时 `AFFECTED_OBJECTS` 查表（常量见下，与 Literal 同源断言防漂移），查不到 id→UnknownCommandError；静态与运行时双门）；Plan.steps 是它的列表。**静态失败测试方式写死**：`tests/typing/expect_errors.py`（basedpyright 扫描该目录、pytest 经 T1 addopts 排除收集，#round11-6）含一行 `PlannedCommand(..., affected_object="bogus")  # pyright: ignore[reportArgumentType]` 对照——正向文件无 ignore 赋值合法八字面量；另用 `assert_never`/`typing.get_args(AffectedObject)` 断言 `get_args` 返回元组恰为八字面量且与 `set(AFFECTED_OBJECTS.values())` 相等。
    - `Document`：metadata v1 **封顶六键**（必填 part_no/revision/material/source 四个字符串 + 可选 part_name/notes 两个字符串；任何其他键由校验层抛 ValidationError，PLM 自定义属性留给未来 schema 版本）；**`new` 文档的 metadata 初值写死**：`part_no=""`、`revision=""`、`material=""`、`source="local"`、无 part_name/notes 键（空字符串是合法值，保证文本脚本路径不写 meta 也能存档；见 #6 的 `meta` 命令）；有序 `list[ExecutedCommand]`；named_groups: dict[str, NamedGroup]（见下 groups.py；CAE 缝：名称+谓词描述子列表，阶段 0 可手工增删、随存档序列化，**不进几何重放序列、不触发 _rebuild**，与 metadata 同为文档注释态）；脏标记；`events` 经信号总线发出。
    - **历史参数编辑 API（#10，唯一入口）**：`Document.replace_command_params(ordinal: int, params: Mapping[str, object], actor: str, reason: str) -> ExecutedCommand`——①经 `self._registry` 取该命令 spec 并以 `validate_params(spec, params, defs=self._registry.schema_defs)` 重新校验（#round11-2/#round11-NB3：Document 构造即持有 registry，见 T3 registry 段；不合法抛 ValidationError，文档不变）；②深拷贝当前命令列表为快照；③替换该 ordinal 的 params 并追加 CommandAmendment（at=UTC ISO8601、from_params=旧参数），**保留原 ordinal/timestamp_utc/confirmed_by 不变**；④发 pre_command/post_command 之外的专用信号 `command_amended`；⑤返回修订后的 ExecutedCommand。几何重放由 Bus 侧方法负责（见下），Document 本方法不改几何。
    - **`Document.set_metadata(key: str, value: str)`（#6 文本路径元数据；唯一入口）**：key 必须 ∈ {part_no,revision,material,source,part_name,notes} 六白名单，未知键 ValidationError；value 必须是字符串；直接改 metadata、置脏、发 `metadata_changed` 信号；**不进命令历史、不参与重放、无 undo 条目**（阶段 0 的元数据是文档属性不是建模命令；save 后随存档持久化）。
  - **`src/mycad/core/groups.py`（NamedGroup 契约，#10；描述子数据类已由 T1 落在 core/selectors.py，故 core 内自洽、无 geom 依赖）**：`@dataclass(frozen=True) NamedGroup(name: str, faces: tuple[FaceSelector, ...] = (), edges: tuple[EdgeSelector, ...] = ())`（从 mycad.core.selectors import 两描述子；name 非空字符串由 Document API 校验；构造时 faces/edges 接收 list 则内部 tuple() 化）。Document API：`add_named_group(group: NamedGroup) -> None`（重名→ValidationError，发 `named_group_added` 信号）、`remove_named_group(name: str) -> None`（不存在→KeyError 由 T10 归运行错误 1，发 `named_group_removed`）；信号 Literal 清单相应扩为 pre_command/post_command/command_amended/metadata_changed/named_group_added/named_group_removed/document_saving/document_saved/geometry_rebuilt。
  - `bus.py`：`CommandBus(document, registry, kernel, handlers: Mapping[str, CommandHandler])`——构造时 handlers 至少含全部已注册命令的处理器（T7 装配 BuiltinModelingHandler，T9 追加插件处理器；未命中处理器抛 UnknownCommandError）；单命令 `execute(command_id, params, confirmed_by=None) -> object | None`：**命令处理流水线在本方法内写死为唯一顺序 `validate_params(spec, params, defs=registry.schema_defs) → normalize_params(params) → handlers[id].handle(normalized, ctx)`（#round11-2：defs 唯一来源=构造注入的 registry.schema_defs，_execute_one/execute_batch/open_document 自动重放同走本流水线同一 defs；Bus 是规范化的唯一调用点；handler 与 geom 只接收已规范化 dict，禁止各自再规范化）**→ 发 pre_command（在 validate 通过之后、handle 之前）→ 取值 → 成功才追加历史（分配 ordinal/时间戳/confirmed_by）→ 发 post_command → 返回处理器值；**任何新命令成功执行都清空 redo 栈**（含 undo 之后再 execute）；`undo(n: int = 1)`：把末尾 n 条命令整体弹出到 redo 栈（保持原顺序）后只做一次 `_rebuild()`（reset 后顺序重放剩余历史；不逐条重放）；`redo(n: int = 1)` 对称弹回 n 条后一次重建。**n 语义写死**：缺省 n=1；n 必须为 ≥1 的整数；历史/redo 栈长度不足 n 时**在任何变更之前**抛 `InvalidHistoryError(action)`，历史与几何保持原子不变（先校验长度再弹栈）；空历史 undo、空 redo 栈 redo 同此异常。CLI 层解析：`undo`/`redo` 无参数=1；非正整数（0/负数）或非整数→CliSyntaxError 退出码 2（用法错误）；栈不足的 InvalidHistoryError→退出码 1（运行错误）。`undo(n)`/`redo(n)` 本身不产生历史条目；
    - **`edit_and_replay(ordinal, params, actor, reason) -> None`（#10 几何侧）**：批前快照（同 execute_batch 的深拷贝纪律）→ `document.replace_command_params(...)`（校验失败直接抛出，几何未动）→ `_rebuild()`：reset 后用修订后的历史顺序重放，**任一步几何失败：恢复快照（params 与修订记录一并回滚）、再 `_rebuild()` 回到编辑前几何，仍失败则抛 `ReplayDuringRollbackError(original=<触发命令的几何异常>, replay_reason=...)`；单次重放失败（回滚成功）把触发命令的 GeometryBuildError/TopologyReferenceError 包装为带 ordinal 的同一异常类型原样抛给调用方**；成功后清空 redo 栈、脏标记、发 geometry_rebuilt。
     - `execute_batch(plan: Plan)`：**前置状态契约=plan.status 必须为 `"confirmed"`**（否则 InvalidPlanTransition）；进入时调 `plan.mark_executing()`（confirmed→executing，边③）→ **批前快照**（深拷贝 commands 列表+metadata，不复制几何）→ 逐条执行，**每条 step 走与单命令相同的 `validate_params → normalize_params → handler.handle` 流水线（复用内部 `_execute_one`，禁止批路径另写一套）；step 经 normalize 后的 params 才是写入历史与 geom 的 params**；`confirmed_by` 统一取 `plan.confirmed_by` 并写入本批每条 ExecutedCommand（见"confirmed_by 权威规则"）→ **全部成功：调 `plan.mark_done()`（executing→done，边⑤）后正常返回**；任一失败：恢复快照 + `_rebuild()` 回滚到批前几何状态、调 `plan.mark_failed()`（executing→failed，边⑥）、**固定且唯一地抛 `BatchRollbackError(failed_ordinal, failed_command_id, reason, executed_ids)`**（executed_ids 为本批已成功执行的命令 id 有序元组；不返回错误对象、不吞异常；失败也先完成状态转移再抛错）；回滚中的 `_rebuild()` 若二次失败，抛 `ReplayDuringRollbackError(original=BatchRollbackError, replay_reason=...)` 保留两者信息；重放途中 TopologyReferenceError 必须原样带命令 ordinal 透传（包装进 BatchRollbackError.reason 链）。
     - **规范化三入口同一顺序（#round7-1，集成测试锁定）**：所有进入 geom 的路径必须经过 Bus 流水线——①交互式/脚本单行走 `execute`；②`begin-batch`/`run --json` 经 `execute_batch` 的 `_execute_one`；③`open_document` 自动重放走 Bus 内部同一 `_execute_one`（存档中的 params 是已规范化形态，仍过 validate_params 做结构校验，normalize 对其幂等）。**禁止 open 重放路径绕过流水线直接调 kernel.apply**。集成测试：一条 `feature.cylinder`（schema 合法形态含 `axis:""` 的谓词位置，例如经孔/圆角路径）经 Bus 执行成功且到达 geom 的 params 中对应值为 None（FakeKernel 记录收到的 dict 断言）；直接把未规范化 dict 喂给 BuildKernel 的旁路测试必须失败/不被产品代码允许（geom 层对 plane 空串有防御性报错即可）。
     - **confirmed_by 权威规则（#round7-6，消除 T6/T10 冲突，全项目唯一）**：①交互式 REPL 与脚本 `run <file.txt>` 的普通建模行——`confirmed_by="cli-local"`（本地 CLI 调用=用户本人隐式确认，必须落审计字段，不得为 null）；②`begin-batch`/`end-batch` 段落——CLI 在 end-batch 时用累积的行构造 `Plan(steps)`，`plan.confirm(actor="cli-local")`，再调 `execute_batch(plan)`，**批内每条 ExecutedCommand.confirmed_by 必须等于 plan.confirmed_by（="cli-local"）**；③`run --json`——计划经 confirm("cli-local") 后 execute_batch，同样每条="cli-local"；④Python API 直接调 `bus.execute(cid, params)` 省略 confirmed_by 时才为 null（程序化调用方自担审计语义，CLI 层永不产生 null）。CLI 测试断言：脚本 3 条普通行 + 1 个 2 行批后 `history --json` 中 5 条命令 confirmed_by 全为 `"cli-local"`。
  - `signals.py`：极简 headless 信号（标准库：订阅 list + 弱引用；**事件类型 Literal 恰好九个（与 groups.py 段的清单逐字一致，本清单是唯一权威）**：`pre_command`/`post_command`/`command_amended`/`metadata_changed`/`named_group_added`/`named_group_removed`/`document_saving`/`document_saved`/`geometry_rebuilt`；测试用 `typing.get_args(SignalName)` 锁定九元组与上述顺序逐字相等，并对 metadata_changed、named_group_added、named_group_removed 各做一次真实触发订阅断言（set_metadata/add_named_group/remove_named_group 各恰好触发一次）；回调异常隔离：一个监听器异常只 warning 不影响其他监听器与主流程——为插件隔离 T9 预埋）。**零 Qt 依赖**。
  - `persistence.py` + `schema_v1.py`：存档 JSON（UTF-8、ensure_ascii=False、indent=2、键序稳定）：`{"format":"mycad.document","version":1,"metadata":{...},"commands":[{"id","version","params","ordinal","timestamp_utc","confirmed_by",("amendments" 仅在非空时出现)}],"named_groups":[{"name","faces":[<FaceSelector JSON>],"edges":[<EdgeSelector JSON>]}]}`——**命令元素完整存六字段+可选 amendments**（`confirmed_by` 取值以 bus.py "confirmed_by 权威规则"为唯一权威：CLI 全部建模路径="cli-local"，仅 Python API 省略时为 null）；**named_groups 元素恰好三键 name/faces/edges（additionalProperties:false），faces/edges 数组元素是附录 A.0 的 FaceSelector/EdgeSelector JSON 形态（**v1 wire 规则（#round8-2）：axis/curve 为 None 时 JSON 中省略该键，绝不写 null——cylinder 分支 schema 允许 axis 缺省，故合法存档=无 axis 键；存档中出现显式 `"axis": null` 属于损坏数据，加载校验固定抛 ValidationError（reason 指向该选择器）**）；空列表显式写出**；
    - **save/open 契约（权威签名与语义，#6）**：`save_document(document: Document, path: Path) -> None`（原子写：写同目录临时文件再 os.replace；写前发 document_saving、写后发 document_saved；path 父目录不存在不自动创建，由 OSError 透传）；`open_document(path: Path, *, registry: CommandRegistry, kernel: Kernel, handlers: Mapping[str, CommandHandler]) -> LoadedDocument`，其中 `LoadedDocument(document: Document, bus: CommandBus)`——**open 恢复数据后立即自动整体 `_rebuild()` 一次**（调用方拿到的文档几何已是重建完成状态；重放不改写任何原 timestamp/ordinal/confirmed_by/amendments）；bus 以注入的 registry/kernel/handlers 装配（自动重放的 validate 经 bus 流水线获取 `registry.schema_defs`，open_document 不单独接收 defs 参数——#round11-2 唯一注入点）。
    - **打开阶段异常映射（闭合于 T1 的 15 类，禁止新增异常类）**：文件不存在由 CLI 层判为退出码 2（open_document 本身不处理路径存在性）；①JSON 语法损坏（json.JSONDecodeError）/顶层非对象/缺必需顶层键或命令元素缺六字段/字段类型错/未知 metadata 键/未知顶层键 → 统一包装为 **ValidationError**（reason 注明 JSON 指针路径）；②`format != "mycad.document"` 或 version 非 1（含未知高 version）→ **ArchiveVersionError**（含读到的 format/version；**字段填充规则写死（#round9-NB-E）**：`ArchiveVersionError(path, found, supported)` 三参——format 不符时 `found`=文件中实际 format 字符串（如 `"mycad.other"` 或缺失时的占位 `"missing"`）、`supported="mycad.document"`；version 不符时 `found`=实际 version 值的字符串形式（如 `"99"`）、`supported=1`；两类用例分别 assert 这两组字段值，禁止混用）；③命令 id 在注入的 registry/handlers 中无处理器 → **UnknownCommandError**（带 ordinal 与 id）；④自动重放中几何失败 → 原样透传带 ordinal 的 **GeometryBuildError/TopologyReferenceError**（不吞、不换类）。
    - **TDD 用例（tests/core，至少四例）**：malformed JSON→ValidationError；未知 metadata 键→ValidationError 且文档对象未被部分构造（异常外无残留）；缺 handler（用最小 registry 故意不注册某 id）→UnknownCommandError 且消息含 ordinal；合法数据但 kernel 对第 2 条抛几何错→GeometryBuildError 带 ordinal=1；`migrations/` 包注册 `Migration(from_version,to_version,fn)` 钩子（v1 无条目，有注册表单测证明未知版本路径报错文案正确）；扩展名 `.mc.json`。
  - `plan.py`（放 core 由 agent 再导出）：`Plan(steps: list[PlannedCommand], status: PlanStatus = "draft", plan_id: str = field(default_factory=lambda: uuid.uuid4().hex), confirmed_by: str | None = None)`（**#round11-4：status 默认值写死 "draft" 且字段序 steps 在前——CLI begin-batch/run --json 的 `Plan(steps)` 构造形式即合法，类型测试锁定字段序与默认值**；plan_id 缺省自动生成 32 位小写 hex；CLI 读计划 JSON 缺 plan_id 时同样走 `uuid.uuid4().hex`，不得用时间戳格式；构造后 plan_id 只读）+ 纯函数转移 `confirm(actor)/mark_executing()/mark_done()/mark_failed()/cancel()`；`PlanStatus` Literal 六态 `draft|confirmed|executing|done|failed|cancelled`；**合法转移恰好 6 条边（本表是唯一权威，禁止"11 边"表述）**：①draft→confirmed（confirm(actor)，必须记录非空 confirmed_by，对空 actor 抛 ValueError）②draft→cancelled ③confirmed→executing ④confirmed→cancelled ⑤executing→done ⑥executing→failed；done/failed/cancelled 为终态。**非法转移表（参数化测试穷举）**：3 终态×6 请求动作全部拒绝；另测 draft→executing、draft→done、draft→failed、confirmed→done、confirmed→failed、executing→confirmed/cancelled 共 8 个跨态跳跃拒绝；非法转移一律抛 T1 清单中的 `InvalidPlanTransition(from_status, requested)`；**没有任何 LLM/网络代码**。
  - 测试 `tests/core/`（**集成测试可用 T5 已交付的真实特征原语**：feature.box/cylinder 三 mode、extrude/revolve/hole/hole_pattern/fillet；完整法兰验收序列仍留 T11）：bus 经 BuiltinModelingHandler execute/undo/redo 后几何查询值一致（用真 BuildKernel 做集成测试；Protocol 另写脚本化 FakeKernel 单测回滚机制本身）；**处理器契约单测**：注册一个返回字符串 `"pong"` 的 FakeHandler（command_id="demo.ping"），经 bus.execute 返回值原样透传且历史照记一条；注册缺失处理器的 id 执行抛 UnknownCommandError；**分派锁定测试**：同一 handler 类 `EchoHandler(command_id)` 分别以 "demo.a"/"demo.b" 构造两个绑定实例（handle 断言 ctx.command_id == self.command_id 并返回该 id），注册后 bus.execute("demo.a") 返回 "demo.a"、execute("demo.b") 返回 "demo.b"，且 ctx.command_id 与映射键不一致的注入（手工构造 HandlerContext 传错 id）必须触发断言/ValueError——锁定"按命令 id 绑定实例"契约，防止退回共享无状态实例；redo 栈在新命令后被清空、空历史 undo/redo 报 InvalidHistoryError；**undo/redo 的 n 参数语义参数化**：默认=1；undo(3) 一次弹 3 条且只触发一次 _rebuild（FakeKernel 计数 reset/apply 次数断言）；redo(2) 对称恢复；n=0、n=-1、n=1.5 在 CLI 层分别为 CliSyntaxError（bus 层 Python API 收 int 即可，非 int 属类型错误）；历史长度不足时 InvalidHistoryError 且变更前历史/几何不变（先执行合法 undo 制造 redo 栈，再 redo(99) 断言栈与几何都未动）；**edit_and_replay 四场景**：①改 cylinder radius 后几何重放为新解析体积（同一 Document、同一命令 ordinal，timestamp_utc 前后字符串相等、amendments 追加 1 条含 from_params）②非法 params（radius=-1）ValidationError 且几何/历史/amendments 均不变 ③重放几何失败（FakeKernel 注入第 2 条失败）时 params 与 amendments 回滚、几何回到编辑前、抛出的异常带 ordinal ④FakeKernel 注入"回滚 _rebuild 也失败"→ ReplayDuringRollbackError(original, replay_reason)；**execute_batch 状态机与回滚**：①成功批断言 plan.status 走完 confirmed→executing→**done**（mark_executing/mark_done 各被调用一次，可用 FakePlan 或状态序列快照）；②两失败场景（第 2 条 validate 失败、第 3 条几何失败）均断言：抛 BatchRollbackError 且 failed_ordinal/failed_command_id/reason/executed_ids 四字段值正确、几何与历史整体回到批前（失败批任何命令都不在历史里）、plan.status="failed"（mark_failed 已调用）；③对 status="draft"/"done" 的 plan 调 execute_batch → InvalidPlanTransition；ReplayDuringRollbackError 批路径用 FakeKernel 注入"回滚重放也失败"单测；重放失效报错带 ordinal；信号订阅/异常隔离（含 command_amended 触发一次）；**存档往返**（save→新 Document.open→rebuild→box/cylinder 几何值一致；六字段+空/非空 amendments 完整恢复，timestamp 前后字符串相等；**NamedGroup 往返**：add 两个组（含 FaceSelector/EdgeSelector 混合）→save→open 后组名/描述子逐字段相等、不触发额外重放、remove 后再存档该键消失、重名 add ValidationError）；**metadata 六白名单**：set_metadata 六键合法、第七键 ValidationError、信号 metadata_changed 触发一次；脏标记；**规范化流水线（#round7-1）**：①含 `axis:""` 的 cylinder 形态谓词参数经 bus.execute（FakeKernel 记录入参）到达 handler 时已是 None；②直接给 FakeKernel/geom 喂未规范化 dict 的旁路在产品代码中不存在（grep 断言 geom 模块不调用 normalize_params、normalize_params 仅 bus 与 T3 测试引用）；③open 重放路径同样经过 validate→normalize（**wire 往返（#round8-2）**：cylinder 选择器无 axis 键的命令 save 后 JSON 文本中不含 axis 键（`"axis" not in raw_json` 断言），open 恢复为缺省且几何一致；手写篡改存档加入显式 `"axis": null` → ValidationError 且文档不被部分构造；同理 EdgeSelector.curve 省略键往返）；**confirmed_by CLI 语义（#round7-6）**：bus.execute(...,confirmed_by="cli-local") 后 history 该命令 confirmed_by=="cli-local"；execute_batch 后批内每条 confirmed_by 等于 plan.confirmed_by（参数化 plan actor="cli-local"/"acceptance-test" 两例）；Python API 省略时为 None；Plan 转移矩阵测试（**6 条合法边逐边各 1 例 + 3 终态×6 动作终态拒绝参数化 + 8 个跨态跳跃拒绝**，confirm("") 空 actor 拒绝）；**性能门（NF-04 量化）**：≤10 命令的 box/cylinder 序列整体重放 10 次，每次墙钟 `< 1000ms`（断言而非仅打印；超时即失败，实测法兰级预期毫秒，为 ADR-002 brep 缓存 v2 留基线）。
  - Must NOT do：不 import geom/formats（双依赖倒置，只持 Protocol）；不做 inverse 命令；不做 BREP 内嵌/快照缓存（ADR-002 演进口）；不做 Redo 以外的多分支历史；不引第三方事件库；不做并发写锁（单线程文档模型，文档注明）；**execute_batch 不允许"返回错误对象/部分成功"语义**；ExecutedCommand/PlannedCommand/AFFECTED_OBJECTS 不在 core 外重复定义。
  Parallelization: Wave 3（单波；集成测试与几何失败场景依赖 T5 真实特征原语）| Blocked by: T3（异常/registry/spec）, T5 | Blocks: T7, T8, T9, T10 | 并行：无
  References:
  - `docs/技术路线.md:30-38`（五原则）、`:155-160`（计划状态机六态原文）
  - `docs/需求分析书.md:101-110`（F-AGT-04 失败事务回滚）、`:71-78`（F-DOC-01..04）、NF-03、NF-04
  - ledger E6（FreeCAD Transaction/.FCStd 对照：v1 轻量重放足够，brep 缓存留演进）、A4/A5/A7/A15/A16、R17
  - ADR-001/002（T4 产物；若 T4 先完成直接引用，否则按本计划描述执行）
  Acceptance criteria:
  - `uv run pytest tests/core -q` 全绿；批回滚两场景中断言"失败批任何命令都不在历史里、几何 volume 回到批前值、BatchRollbackError 四字段完整"；存档往返 box/cylinder 几何值一致且六审计字段完整恢复；Plan 恰好 6 条合法边逐边覆盖 + 3 终态×6 动作拒绝参数化 + 8 跨态跳跃拒绝全部覆盖；重放性能门 <1000ms×10 全过。
  - `python -c "import mycad.core" ` 不触发 build123d/OCP 加载（专用测试 `tests/test_core_isolation.py`：**必须在全新子进程中断言（#round7-NB6，用 subprocess.run([sys.executable,"-c",...])），不得在主 pytest 进程内查 sys.modules——geom 用例会先污染模块状态**；子进程内 import mycad.core 后断言 "build123d" not in sys.modules and "OCP" not in sys.modules，并附反向自证：import mycad.geom 后两模块确实出现，证明断言有效力）。
  QA scenarios:
  - happy：内联脚本走 new doc → 用 box/cylinder/add 三命令建组合体 → undo 两次后体积断言回到中间态 → redo → save /tmp/out.mc.json → 新 doc open+rebuild → 体积一致、六字段完整，输出存 `.omo/evidence/task-6-phase0-mvp.md`。
  - failure：批中第 2 条给非法半径（validate 失败）与第 3 条几何失败（kernel 抛错）两场景，均要求整体回滚、plan.status=failed、抛 BatchRollbackError 且含 failed_ordinal/failed_command_id/executed_ids；**open 失败矩阵四例**：手改 version=99→ArchiveVersionError（assert found="99", supported=1）、手改 format 字符串→ArchiveVersionError（assert found=实际串, supported="mycad.document"，#round9-NB-E 两场景字段分别断言）、损坏 JSON 与未知 metadata 键→ValidationError、缺 handler id→UnknownCommandError 含 ordinal、kernel 重放第 2 条失败→GeometryBuildError 含 ordinal；输出附证据。
  Commit: Y | `feat(core): document, command bus with replay undo and batch rollback, signals, json archive v1, plan state machine`

- [x] 7. T7 八条内置命令接线（id 逐字对齐 UI 初稿 §5.3）+ 组合根
  What to do / Must NOT do:
  - 新建固定包路径 **`src/mycad/builtin_commands/`**（不得使用 commands/builtin/ 等别名路径；与注册表框架分包，防止插件机制与内置耦合）：为 8 条命令各定义 CommandSpec(version=1, undo_compensation="history_replay")，字段严格按 T3 签名——`summary_en`（英文，CLI help 实际消费）与 `label_zh`（中文标签数据，阶段 0 无消费者但必须填全）；8 条命令的 params_schema **逐字采用文末附录 A**，且 schema 中所有共享对象一律以 `"$ref": "#/$defs/<Name>"` 引用本包内**单一常量表文件 `src/mycad/builtin_commands/defs.py` 的符号 `COMMAND_SCHEMA_DEFS`（#round9-7：路径与符号名写死，AST 断言全 src 无第二处 `COMMAND_SCHEMA_DEFS =` 赋值，T3 校验器经 defs 参数解析、本 todo 调用 validate_params 时注入此表；禁止在各命令 schema 内复制粘贴子结构）**：
    1. `feature.box`（size_x/size_y/size_z >0，center 三元组 default 0，mode new/add/cut）
    2. `feature.cylinder`（T3 已示范，迁移到本包注册）
    3. `feature.extrude`（profile: {type:"circle"|"rect", ...参数}，distance 带符号数值，mode）
    4. `feature.revolve`（profile，axis: "X"|"Y"|方向三元组，angle_deg 0<..≤360 default 360，mode）
    5. `feature.hole`（params_schema=根级 `{"$ref": "#/$defs/Hole"}`（#round11-3）；target_face: FaceSelector JSON 对象；position v1 仅 `{"kind":"center"}`；diameter>0；depth: {kind:"through_all"}|{kind:"blind",value>0}）
    6. `feature.hole_pattern`（base_hole=`{"$ref": "#/$defs/Hole"}`（#round11-3：经 $ref 复用，禁止内联复制子结构）——含自己的 target_face 谓词，法兰场景=最大 +Z 面 center；+ pattern:{kind:"polar",radius>0,count:int 2..64,start_angle_deg default 0}；kind=linear 被拒绝）
    7. `modify.fillet`（edges: EdgeSelector 数组，radius>0）
    8. `modify.boolean_cut`（tool: 内联原型体描述 {type:"cylinder"|"box",...}；阶段 0 不支持引用另一实体名，docstring 说明；**不是法兰中心孔的实现路径**）
  - 每条命令有 params schema、CLI 动词别名（box/cylinder/extrude/revolve/hole/hole-pattern/fillet/cut，**`cut` 仅为 modify.boolean_cut 别名**）、`to_cli` 稳定输出（**键序规则唯一 owner=T3（#round9-NB-C/#round10-NB2）：输出键的顺序=该命令 params_schema 中 `properties` 的声明顺序（含嵌套对象按其 schema properties 顺序、数组元素内部同理）；规则在 T3 的 `to_cli` 实现处定义唯一权威，T7 仅消费 T3 的 to_cli、不得另立规则，T10/T11 快照只引用 T3 输出；保证脚本/日志可 diff，NF-03；嵌套按 T3 扁平点键文法）。
  - `src/mycad/plugins/types.py`（**本 todo 创建该文件并定义全部跨波公开符号；T9 只 import 消费并在其他文件加实现，不得在此文件增删改任何字段——#round9-4 所有权写死**）：本 todo 在此唯一定义并导出插件机制的全部公开契约（T7 的 build_app 签名需要它们，放 W5/T7 所有方可消除 T9→T7 签名反向依赖；T3 的 CommandSpec、T6 core.handlers 的 CommandHandler 均已在更早波次存在，导入方向合法）：⓪**`CommandContribution`（唯一定义处，#round9-4：消除"除 T9 段定义"的矛盾）**：frozen dataclass `CommandContribution(spec: CommandSpec, handler_factory: Callable[[], CommandHandler] | None)`（从 T3 `mycad.commands.spec` import CommandSpec、从 T6 `mycad.core.handlers` import CommandHandler；demo 插件与所有测试均从 `mycad.plugins.types` import；AST/路径断言拒绝 discovery.py/loader.py/manifest.py/app.py 中出现第二个 class CommandContribution 定义）；①`PluginDiscoverer(Protocol)`：`discover() -> Sequence[DiscoveredPlugin]`（零参；T9 提供唯一实现 `EntryPointDiscoverer`，内部扫 importlib.metadata 两个 entry 组）；②`@dataclass(frozen=True) DiscoveredPlugin`（**字段恰好六个，写死**：`distribution_name: str`、`entrypoint: tuple[str, ...]`（该 distribution 命中的 entry-point 引用字符串去重+字典序，格式 `<group>:<module>:<attr>`，单 entry 一元组；#round7-4）、`manifest: PluginManifest | None`（manifest 缺失/损坏时为 None）、`commands: tuple[CommandContribution, ...]`（本插件经 api 门控后的命令贡献，默认空元组）、`formats: tuple[FormatProvider, ...]`（provider 工厂零参实例化、priority 去重后的结果，默认空元组）、`warnings: tuple[str, ...]`（人读跳过原因码，默认空元组））；③**PluginManifest（frozen dataclass，字段与类型写死，执行者零发明）**：`id: str`（非空、^[a-z0-9_.-]+$）、`version: str`（插件自身版本，非空 str，不做强制 SemVer 解析）、`api_version: str`（**唯一规则=主版本兼容（#round8-3，消除"恰好等于 1.0"矛盾）**：加载条件写死为 `int(api_version.split(".", 1)[0]) == CURRENT_API_MAJOR`，即 `"1.0"`/`"1.5"` 等任意 1.x 均加载、`"2.0"` 及以上或不可解析（split 后首段非 int/无点单段非整数）→ 跳过，reason=`incompatible-api`；禁止再出现"必须恰好等于 1.0"表述）、`permissions: tuple[str, ...] = ()`（阶段 0 只做存储与 `plugins` 子命令展示，不强制执行任何权限；未知权限串不报错）、`homepage: str = ""`（可选，仅展示）；模块常量 **`CURRENT_API_VERSION = "1.0"`** 与 `CURRENT_API_MAJOR = 1` 同处定义，`mycad.plugins.__init__` 再导出；⑤**跳过原因码穷举集（#round9-5，T9 warning 与 T10 `plugins` 输出共用同一常量）**：同文件定义 `WARNING_REASON = Literal["missing-manifest","manifest-error","incompatible-api","command-conflict","provider-conflict","load-error"]` 与等值的运行时冻结集合 `WARNING_REASONS`（`typing.get_args(WARNING_REASON)` 与集合元素逐字相等的锁定测试放 T7）；任何跳过事件的 reason 必须取自该六值——`missing-manifest`=模块无 manifest 属性、`manifest-error`=manifest callable 抛错或返回值损坏（缺/多/错类型字段）、`incompatible-api`=主版本不兼容或不可解析、`command-conflict`=命令 id 与内置或已加载插件冲突、`provider-conflict`=FormatProvider 同 priority 扩展名重叠（ProviderConflictError 被捕获后按条目跳过）、`load-error`=entry 加载/工厂调用抛错（含格式工厂与处理器工厂）；T9 不得发明第七个码、T10 `plugins` 输出的 reason 占位符引用本 Literal；④**manifest() 定位算法（#round7-4，写死）**：**不新增第三个 entry-point 组**——对每个贡献 entry（`mycad.commands`/`mycad.formats` 的 EntryPoint 对象），取其 `EntryPoint.module`，用 `importlib.import_module(module)` 导入该模块，在**模块属性**中按固定名字 `manifest` 查找：可调用（零参）则调用一次并取返回值、直接是 dict/PluginManifest 也接受（dict 经 PluginManifest(**d) 构造，字段缺失/多余/类型错→损坏）；同一 distribution 的多个 entry 指向同一 module 时只导入/调用一次（按 module 名 memoize）；缺失 `manifest` 属性、调用抛异常、返回值损坏三类分别记 reason `missing-manifest`/`manifest-error`/`incompatible-api`（后者优先：能解析但主版本不符）；manifest 缺失/损坏时该插件所有贡献跳过（commands/formats 均为空元组）；⑤**多 entry 合并时 `DiscoveredPlugin.entrypoint` 字段语义改死**：类型 `tuple[str, ...]`（不再是单 str），值=该 distribution 命中的 entry-point **引用字符串去重后按字典序排列**，格式标准 entry-point 表示 `"<group>:<module>:<attr>"`（attr 缺省省略），单 entry 时为一元组；同步把字段名保留为 `entrypoint` 但类型标注逐字写死；字段级测试覆盖：单组单 entry、双组各一 entry（合并一元组变二元组）、同 module 双 entry memoize 只调一次 manifest；④**`PluginManager`（本 todo 在 `src/mycad/plugins/manager.py` 定义的薄包装，T9 不得改构造签名）**：`PluginManager(discovered: Sequence[DiscoveredPlugin] = ())` frozen 持有 `discovered_plugins: tuple[DiscoveredPlugin, ...]`，方法 `loaded() -> tuple[DiscoveredPlugin,...]`（manifest 非 None 且未被整体跳过者）、`skipped() -> tuple[tuple[str,str],...]`（(distribution_name, reason-code)）、`command_contributions() -> tuple[CommandContribution,...]`、`format_providers() -> tuple[FormatProvider,...]`（后两者供 new_document 工厂与 FormatProviderRegistry 装配遍历）；T7 以空发现构造，T9 的 EntryPointDiscoverer 结果由 build_app 在 T9 接线时注入同一构造器。`mycad.plugins.__init__` 再导出 PluginDiscoverer/DiscoveredPlugin/CommandContribution/PluginManifest/PluginManager/CURRENT_API_VERSION。
  - `src/mycad/app.py`（组合根 composition root）：**`AppServices` frozen dataclass 字段恰好四个（写死，执行者不得增减）**：`registry: CommandRegistry`、`kernel: BuildKernel`、`formats: FormatProviderRegistry`、`plugins: PluginManager`（T9 新增的薄包装：持有 `tuple[DiscoveredPlugin, ...]` 与 loaded/skipped 视图方法；本 todo 先用空发现结果构造）；**Document/CommandBus 不进 AppServices**（文档有 new/open 生命周期，多文档是阶段 1 方向）：由工厂函数 `new_document(services: AppServices, *, confirmed_by: str | None = None) -> LoadedDocument` 与 T6 `open_document(path, registry=..., kernel=..., handlers=...)` 按当前文档实例创建，`LoadedDocument(document, bus)` 定义归 T6。**kernel 是跨文档复用单例，故 `new_document` 在装配 handler 映射后、返回 LoadedDocument 前必须调用且仅调用一次 `services.kernel.reset()`，保证新文档几何为空（不依赖调用方记得 reset）**；CLI `new` 子命令与 `run --json` 的隐式新建文档都必须调用且只允许调用这同一个工厂，禁止各自直接构造 Document/Bus。`build_app(discoverers: Sequence[PluginDiscoverer] | None = None) -> AppServices`：构造 registry——**`CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)`（#round11-2：从本包 defs.py import 单一常量表注入，此后 bus/Document/open/run --json/validate 全路径的 defs 均经此 registry 获得，build_app 是 defs 与运行时的唯一接合点）**，**8 条内置命令在此显式 Python 注册，绝不经过 entry_points**（entry_points 组仅供第三方插件，避免自举歧义；T9 接线 discoverers，本 todo 默认空列表）、BuildKernel（单例，跨文档复用）、handlers 映射（按 T6 契约：8 条建模命令各一个 `BuiltinModelingHandler(cid)` 绑定实例，第三方处理器由 T9 discoverers 追加进 registry 后的新文档工厂使用——handler 映射在 new_document 时从 registry+插件贡献装配，build_app 只持有静态部分），并 **import T8 产物的具体 FormatProviderRegistry，构造 STEP/STL provider 实例后注入**（build_app 是唯一知道全部具体类型的组合根；core 不 import formats、formats 不 import geom）；返回不可变 services 容器。**这是 layering 守卫唯一的 src 例外**：app.py 允许同时 import geom 与 core（在守卫测试中把 `src/mycad/app.py` 单列白名单，其余规则不变；app.py 仍不得直接 import build123d/OCP/numpy）。
  - `src/mycad/agent/`：**仅有 `plan_types.py`**（从 core 再导出 Plan/PlannedCommand/状态转移纯函数，作为协议占位）；**零网络/零 LLM/无 schema_catalog.py/无任何工具 schema 生成代码**（工具面形态只存在于 ADR-004 与附录 A 文字规范，阶段 2 才落地）。
  - 测试：8 条命令各自注册/schema 与附录 A 逐字段相等断言/CLI 往返（`parse_line(text, registry)`/`to_cli(id, p, registry)` 全部传入 build_app 的 registry）/真实几何执行一条最小路径；未知 id 执行抛 UnknownCommandError；`feature.hole_pattern` 产出法兰孔；**AppServices/插件契约字段级锁定**：`dataclasses.fields(AppServices)` 名字元组逐字等于 `(registry,kernel,formats,plugins)`、`DiscoveredPlugin` 六字段逐字锁定、`PluginDiscoverer`  Protocol 仅有 `discover` 方法、`new_document(services)` 返回的 LoadedDocument.document/bus 均可用且新文档 metadata 初值符合 T6（part_no/revision/material=""、source="local"）；**`mycad.plugins.types.CommandContribution` 可被 T3/T6 类型正确构造（#round9-4 验收）**：用一个 T3 CommandSpec 与 `handler_factory=None`/零参返回 T6 CommandHandler 实例的工厂两种形态各构造一例；AST 断言 CommandContribution 的 class 定义在全 `src/` 仅 `src/mycad/plugins/types.py` 一处；**WARNING_REASON 锁定（#round9-5）**：`typing.get_args(WARNING_REASON)` 逐字等于六码元组且与 `WARNING_REASONS` 集合相等，T9/T10 源码中出现的所有 reason 字符串字面量都是该集合成员（AST 字符串扫描测试放 T7，T9 接线后必须仍绿）；**跨文档隔离**：对第一个 LoadedDocument 的 bus 执行 feature.box 后 mass_properties.solid_count=1，再 `new_document(services)` 得到的第二个文档 mass_properties.solid_count=0、volume=0.0（断言工厂内 reset 生效；`run --json` 隐式 new 走同一工厂）；`agent` 包公开面仅有 Plan 相关导出的断言；**`AFFECTED_OBJECTS` 静态断言（附录 B.2 权威表）**：恰好 8 键且与注册表 id 集合相等、`len(set(AFFECTED_OBJECTS.values())) == 8`、值集合逐字等于 `{"box_body","cylinder_body","extruded_body","revolved_body","hole","hole_pattern","edge","tool_body"}`；PlannedCommand 构造传表外字符串在静态类型与运行时均失败（逐字字符串字面量参数化测试）。
  - Must NOT do：不注册 P1/P2 命令（chamfer/shell/union/intersect/pattern_linear/mirror/draft/sweep/datum.*）——id 不得提前占用但 ADR-003 说明命名空间保留；不在命令模块直接 new BuildKernel（经 app 注入）；不写 UI/LLM/MCP 代码/工具 schema 代码。
  Parallelization: Wave 5 | Blocked by: T3, T5, T6, **T8（build_app 必须 import 具体 FormatProviderRegistry 构造注入，禁止 import 环：T8 单走 W4）** | Blocks: T9（app.py 同文件）, T10, T11 | 并行：无（W5 单波）
  References:
  - `docs/UI设计初稿.md:160-185`（P0 id 表逐字）、`:146-148`（命名与分类按表）
  - `docs/技术路线.md:155-160`（协议）；工具 schema 未来形态以本计划**附录 A**与 ADR-004 为唯一文字规范，E8（小工具面/native template）仅阶段 2 相关
  - T3 产物（spec/registry/grammar/校验器 oneOf）、T5 产物（kernel 原语签名）、T6（bus/app 注入需求）
  Acceptance criteria:
  - `uv run pytest -q` 全绿；`uv run python -c "from mycad.app import build_app; a=build_app(discoverers=[]); print(sorted(c.id for c in a.registry))"` 输出恰好 8 个 id，与 UI 初稿逐字一致（断言列表相等的测试；**#round11-NB7：显式 `discoverers=[]` 隔离——即使环境已 editable 安装 demo 插件（T9 接线后），本计数仍恰好 8 且无执行顺序依赖**）。
  - 每条命令至少：1 个合法执行测试 + 1 个校验失败测试 + grammar 往返断言；schema dict 与附录 A 静态比对；无 P1/P2 id 泄漏。
  QA scenarios:
  - happy：脚本经 AppServices 执行 8 命令最小序列（其中孔阵列复用法兰参数），体积=36794.3331588437（math 公式直算，容差 1e-6）；证据 `.omo/evidence/task-7-phase0-mvp.md` 含 8 id 列表与 help 文本。
  - failure：`execute("feature.sweep", ...)` 必须 UnknownCommandError；`modify.fillet` 给线性 pattern 残留参数必须 ValidationError 拒绝多余键；附证据。
  Commit: Y | `feat(commands): eight built-in P0 commands wired through registry and composition root`

- [x] 8. T8 FormatProvider 注册表 + STEP 写/STL 写 provider（STEP 读仅测试辅助）
  What to do / Must NOT do:
  - `src/mycad/formats/base.py`：frozen dataclass `FormatProvider(name: str, vendor: str, priority: int, extensions: tuple[str,...], can_read: bool, can_write: bool, target: Literal["shape","xcaf"], _writer: Callable[[ExportableKernel, Path], None])`，其中 **`ExportableKernel` 从 `mycad.core.ports` import（T6 定义的唯一中立 Protocol，本 todo 不得另立 GeometryExporter、不得重复定义）**：暴露 reset/apply/mass_properties/export_step/export_stl，由 T2 的 BuildKernel 结构化满足（T8 组合时直接传 kernel）。**FormatProvider 直接实现 T6 的 `FormatPort`：dataclass 上定义方法 `write(geometry: ExportableKernel, path: Path) -> None`（方法体调 `self._writer(geometry, path)`；禁止模块级 write 函数、禁止 `params` 参数——阶段 0 写 STEP/STL 无写选项，未来扩展经新字段而非 params 字典）**；`_writer` 为构造时注入的闭包（STEP provider 闭包内调 `geometry.export_step(path)`，STL 同理），故 formats 不 import geom，build123d 调用仍全在 geom io 模块内。formats 只 import core；**阶段 0 产品面无 read 方法**（无 ImportedGeometry 返回值）；`ImportKind` 枚举 DUMB_SOLID/ASSEMBLY_WITH_ATTRS/EDITABLE_FEATURES 仍在本模块定义（ADR-005 词汇表/阶段 1 导入分级用），并有守卫测试断言"src 中不存在任何返回 EDITABLE_FEATURES 的代码路径"（grep/AST 断言）。
  - `registry.py`：`FormatProviderRegistry(providers: Iterable[FormatProvider] = ())` 实现 T6 的 **`FormatResolver`**：`register(provider)`/`get_by_extension(ext)`/`list_providers()` + **`resolve(path: Path) -> FormatPort`**（按扩展名解析，等价于 get_by_extension 但返回类型标注为 FormatPort）；解析规则：同扩展名多个 provider 时取 `priority` 最小值；**priority 相同且扩展名重叠 → register 时抛 T1 清单中的 ProviderConflictError(extension, (name,vendor), (name,vendor))（命令 id 冲突才用 CommandConflictError，两者签名不通用）**。一致性测试：`isinstance(registry.resolve(tmp/"f.step"), FormatPort)` 通过、解析返回对象的 `.write(geometry, path)` 能实际写文件（用 STEP/STL 各一次端到端断言）。
  - `providers/step_provider.py` 与 `stl_provider.py`：STEP provider 固定 `name="STEP", vendor="OCC", priority=100, can_read=False, can_write=True, target="shape"`（命名对齐 E10 DE_Wrapper），write 经 geom kernel 的 `export_step(path)`（geom io 模块持有 build123d 调用，build123d 对象不越 geom 边界；为阶段 1 读路径预留独立 reader 参数实例纪律，ADR-005 已记）；STL provider `name="STL", vendor="OCC", priority=100, can_read=False, can_write=True, target="shape"`；STEP provider 同样 `target="shape"`（FormatProvider.target 必填，阶段 0 两 provider 逐字固定该值，"xcaf" 仅为阶段 1 装配导入预留字面量）；**对空几何导出 STEP/STL 必须抛 T1 清单中的 EmptyGeometryError（专用失败用例），不得写出空文件**。
  - **STEP 读回只允许存在于 `tests/helpers/step_roundtrip.py`**：该辅助函数可直接 import build123d 的 import_step（已在 T2 layering 白名单），仅供"导出→读回"往返断言使用；**不产生文档历史节点、无 `document.import_step` id、无导入异常产品类型、缺文件用内置 FileNotFoundError**；产品化 STEP 导入是 F-DOC-03/阶段 1（ADR-005 Consequences 注明）。
  - 导出为不经 Bus 的只读服务：`export(document/kernel query, path)` 从当前几何导出，**不进历史、不脏标、不发建模信号**（CLI/未来 MCP 均可调）。
  - 测试 `tests/formats/`：法兰几何导出 STEP 后用 `tests/helpers` 读回，solid 数/体积一致（1e-6）；未知扩展名 get_by_extension 抛 UnknownFormatError；STL/STEP 两 provider 均 can_read=False 的断言；空几何导出 EmptyGeometryError；priority 选择测试（注册 priority=50 的伪 provider 后解析到它）与同 priority 冲突抛 ProviderConflictError；Windows 路径（纯 pathlib + tmp_path，CI Windows job 验证）与中文路径测试（tmp 下建 `目录/flange_法兰.step`）。
  - Must NOT do：不实现 read 产品路径/`document.import_step`/imported_solid 节点/ImportSourceMissingError；不实现 IGES/glTF/BREP/3MF/DXF（ADR-005 有序列，阶段 0 不做）；不碰商业格式与 DWG；不让 OCP 类型出现在 formats 公开签名（只出现 geom 的中立 DTO/查询结果与 path）；不把导出写进命令历史。
  Parallelization: Wave 4（单波；T7 的 build_app 要 import 本 todo 的具体注册表，必须先于 T7 完成）| Blocked by: T2（geom kernel 的 export_step/export_stl 占位与 mass_properties——T2 先占位 NotImplemented、本 todo 在 geom io 模块接线实现）, T5（法兰形几何由特征命令产出，供导出验收）, T6（core.ports 的 ExportableKernel/FormatPort/FormatResolver 约定、T1 异常清单）| Blocks: T7, T10, T11 | 并行：无
  References:
  - ledger E10（OCCT 7.8 DE_Wrapper：FormatName×VendorName、VendorName="OCC"、STEP AP242、reader 参数独立、glTF/3MF 依赖情况）、E5（商业墙）、E11 尖刺 export_step 24390B/export_stl 152084B/import_step 往返（读回仅测试用途）
  - `docs/需求分析书.md:71-78`（F-DOC-02 导出阶段 0；F-DOC-03 导入为 P1/阶段 1，本 todo 不产品化）、`docs/技术路线.md:62`（geom 导入导出职责，读路径阶段 1 接线）
  - ADR-002（无导入节点）、ADR-005（priority/三级/读路径阶段 1）、A17、R11
  Acceptance criteria:
  - `uv run pytest tests/formats -q` 全绿（含 Windows job）；golden 法兰导出 STEP>10KB、STL>1KB（与尖刺同量级）；经测试辅助读回体积 1e-6 一致；priority/冲突/空几何/未知格式各 ≥1 断言；`EDITABLE_FEATURES` 无返回路径的守卫测试存在。
  - formats 包 AST 不出现 build123d/OCP import；`tests/helpers/step_roundtrip.py` 是 tests 中唯一 import build123d 读 API 的位置（layering 白名单测试断言）。
  QA scenarios:
  - happy（#round10-1：禁用 T7 才交付的 AppServices/build_app，本 todo W4 只允许使用 T2/T5/T6 已交付符号）：测试直接 `kernel = BuildKernel()` 并按法兰序列调用 T2/T5 的 `kernel.apply(...)`（cylinder new + feature.hole + feature.hole_pattern，等价 T11 几何参数），再直接构造 T8 本 todo 的 `FormatProviderRegistry([step_provider, stl_provider])` 并以其 FormatResolver.resolve(path) 取得 FormatPort → `port.write(kernel, tmp_path/"flange.step")` / `.stl`（kernel 满足 T6 core.ports.ExportableKernel 结构契约）→ 测试辅助读回断言体积；**测试源码不得出现 AppServices/build_app/new_document**（AST 守卫）。文件大小与体积输出存 `.omo/evidence/task-8-phase0-mvp.md`。
  - failure：导出 `.x_t`/`.dwg` 必须 UnknownFormatError 且错误消息不承诺支持；对空文档导出必须 EmptyGeometryError 且无文件产生；注册两个 priority 相同的 .step provider 必须 ProviderConflictError 且异常含扩展名与两 provider 的 name/vendor；附证据。
  Commit: Y | `feat(formats): prioritized provider registry with STEP and STL writers; test-only STEP readback`

- [ ] 9. T9 插件扩展缝：entry-points 发现 + manifest/api_version 门控 + 信号钩 + 最小自测插件
  What to do / Must NOT do:
  - `src/mycad/plugins/manifest.py`（**仅加载实现**：PluginManifest dataclass 与 CURRENT_API_VERSION/CURRENT_API_MAJOR 的唯一定义在 T7 的 `plugins/types.py`，本 todo 不得在此重复定义/重复赋值——从 types import 消费）：**manifest 定位算法以 T7 types.py 段为唯一权威（#round7-4：importlib 导入每个贡献 entry 的 `EntryPoint.module`、查模块属性 `manifest`、按 module memoize、callable/dict/dataclass 三形态、缺失/损坏/api 不兼容三类 reason）**，本模块只实现该算法；api_version 语义=主版本 ==1 才加载（1.x 兼容，2.x 跳过）。
  - `src/mycad/plugins/types.py`（插件作者的唯一公开导入点；**T7 已创建并唯一定义全部公开名（含 CommandContribution/PluginDiscoverer/DiscoveredPlugin/PluginManifest/CURRENT_API_VERSION/CURRENT_API_MAJOR/WARNING_REASON/WARNING_REASONS），本 todo 对该文件零修改、只 import（#round9-4/#round9-5）**）；`CommandContribution(spec: CommandSpec, handler_factory: Callable[[], CommandHandler] | None)` 从 `mycad.plugins.types` import（禁止在 discovery.py/loader.py/manifest.py 重复定义）；`mycad.plugins.__init__` 再导出由 T7 落地，本 todo 仅在需要时补 EntryPointDiscoverer 导出。
  - manifest 加载实现（T7 已在 `plugins/types.py` 给常量/数据类/定位算法权威描述，本 todo 在 `plugins/manifest.py` 只写加载器实现，不得另立定位规则）：缺失/抛错/返回值损坏/api_version 主版本不兼容分别收集 warning，reason 必须逐字取自 T7 的 `WARNING_REASONS`（`missing-manifest`/`manifest-error`/`incompatible-api`，禁止字符串散落或新造码）；主版本门控常量在 T7 types.py，本 todo 只消费。
  - `discovery.py`：**`EntryPointDiscoverer(groups: tuple[str, ...] = ("mycad.commands", "mycad.formats"))` 实现 T7 定义的 `PluginDiscoverer` Protocol**（唯一方法 `discover() -> tuple[DiscoveredPlugin, ...]`），经 `importlib.metadata.entry_points(group=...)` 扫描；同一 distribution 同时出现在两个组时合并为**一个** DiscoveredPlugin（commands/formats 分列、warnings 合并，distribution_name 不重复）；发现顺序按 distribution_name 排序保证确定性；组名 `mycad.commands`（**entry callable 返回 `list[CommandContribution]`；CommandContribution 为 frozen dataclass `(spec: CommandSpec, handler_factory: Callable[[], CommandHandler] | None)`——单 entry 同时携带命令 spec 与可选处理器工厂，禁止再拆第二个 entry 组**）、`mycad.formats`（**唯一权威契约写死**：`EntryPoint.load()` 零参返回一个零参工厂 `f: Callable[[], list[FormatProvider]]`；装配时核心恰好调用一次 `f()`，返回值必须是 list（可为空 list），核心遍历该列表逐个注册；**禁止 entry 直接返回 provider 实例、禁止返回单个 FormatProvider、禁止工厂带参数、禁止核心做任何扁平化猜测或单对象特判**；每个 provider 实例自带 `_writer` 闭包且八字段 name/vendor/priority/extensions/can_read/can_write/target/_writer 齐全）；handler_factory 省略（None）时核心用 T6 的 BuiltinModelingHandler 兜底（适用第三方声明的普通建模命令）；每个贡献 entry 的模块（`EntryPoint.module`）按 T7 段的模块属性 `manifest` 算法定位清单（callable/dict/dataclass 三形态、按 module memoize），缺 manifest/调用异常/返回值损坏/api_version 不兼容=**跳过该插件、收集 warning 字符串、绝不影响核心启动**。**mycad.formats 加载失败语义**：工厂调用抛异常→该插件的格式贡献整体跳过+warning（同插件命令贡献不受影响，反之亦然，按 entry 组隔离）；provider 注册进 FormatProviderRegistry 时若 priority 相同且扩展名重叠→T8 注册表抛 ProviderConflictError，loader 捕获后跳过**该 provider 条目**（不跳过整个插件）+warning 含两 provider 的 name/vendor。该贡献契约必须在 ADR-003 写死（T4 补一段：插件可提供命令 spec + 处理器工厂、格式 provider 工厂列表；处理器须实现 T6 CommandHandler Protocol；provider 须满足 T6 FormatPort；核心按 api_version 主版本门控后才实例化）。
  - `loader.py`：在 AppServices 装配时调用（T7 的 app.py 预留发现器接口本 todo 接线）；插件加载顺序按 distribution 名排序保证确定性；插件命令 id 与内置或彼此冲突 → CommandConflictError 按"跳过该插件条目+warning"处理（reason 字符串固定取自 `WARNING_REASONS` 的 `command-conflict`），核心不崩；**所有 warning reason 必须是 T7 `WARNING_REASON` 六值之一（#round9-5）**。
  - 信号钩（T6 signals）：文档示例与测试证明插件可订阅 pre_command/post_command/document_saving/document_saved；监听器异常隔离已在 T6 预埋，本 todo 加集成测试：插件回调抛异常时后续命令仍正常执行。
  - **最小自测插件**：放在仓库 `plugins_examples/mycad_plugin_demo/`（独立子目录、独立 pyproject.toml，不进主包依赖、不在 hatchling 打包列表、不进 wheel），注册一条演示命令 `demo.ping`（**CommandSpec 完整值写死（#round8-NB2）**：id="demo.ping"、version=1、summary_en="Ping the demo plugin"、label_zh="演示：心跳"、cli.verb_aliases=("ping",)、params_schema={"type":"object","properties":{},"required":[],"additionalProperties":false}（零参数）、undo_compensation="history_replay"；**经 CommandContribution 提供 `DemoPingHandler`（实现 T6 CommandHandler：command_id="demo.ping"，handle 无视 params 返回字符串 `"pong"`）**，bus.execute 透传返回值，测试经 bus.execute 断言 == "pong"；不引入通用结果对象、不写几何）与一个 `.txt` 伪格式 provider（经 `mycad.formats` entry 的零参工厂返回单元素 list，**FormatProvider 八字段逐字写死**：name="TXT-SUMMARY"/vendor="demo"/priority=100/extensions=(".txt",)/**can_read=False**/can_write=True/**target="shape"**/_writer 写一行体积摘要）；**provider 字段完整性测试**：对 demo 与夹具内每个 provider 实例用 dataclasses.fields 断言 T8 八字段全部存在且类型正确（can_read 为 bool、target∈{"shape","xcaf"}），另测工厂返回空 list（正常零注册）与单元素 list 各一例；经 `tests/plugins/test_demo_installed.py` 的唯一安装纪律（#round12d-2：安装/卸载命令与流程唯一来源=下条 #round9-6/#round11-NB6 写死的 `sys.executable -m pip install -e`，本句不另立安装路径）安装 demo 后断言 build_app() 能发现它、FormatResolver.resolve(x.txt) 返回的对象 `isinstance(..., FormatPort)` 且 `.write(kernel, path)` 实际写出摘要文件；夹具中另加一个同 priority=.txt 冲突 provider 断言注册时抛 ProviderConflictError 且该 provider 被跳过+warning（demo 的命令 demo.ping 仍可用=按条目隔离）；另做 `mycad_plugin_future`（api_version="9.9"）与坏插件（manifest 抛异常）两个测试夹具，**只存在于 `tests/fixtures/plugins/`（测试期源码夹具，不发行、不进 wheel、绝不 editable 安装）**；**#round10-NB3 其加载方式写死为纯进程内 monkeypatch（零安装/零卸载命令）**：夹具是含 `pyproject.toml`+entry 声明+模块源码的普通目录树，测试用 `monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)`（fake 返回由 `importlib.metadata.EntryPoint(name, value, group)` 直接构造、`EntryPoint.load()` 用 `importlib` 从夹具 sys.path 动态导入的对象——conftest 以 `tmp_path`/夹具绝对路径 insert sys.path 并在 teardown 移除，不调用 pip、不写 site-packages），分别构造 future/坏 manifest 两类 EntryPoint 序列喂给 EntryPointDiscoverer，断言跳过+warning；禁止要求执行者真的 `pip install` 这些夹具（与 demo 插件的真 editable 安装测试 test_demo_installed.py 显式区分）；断言跳过+warning；**manifest 发现算法字段级测试（#round7-4）**：①demo 插件模块提供模块属性 `manifest`（dict 或零参 callable 两形态各一夹具），发现结果 DiscoveredPlugin.manifest 五字段 id/version/api_version/permissions/homepage 逐字锁定；②同一 distribution 同时提供 mycad.commands 与 mycad.formats 两个 entry 指向同一模块→合并为一个 DiscoveredPlugin，`entrypoint` 为去重排序后的二元组、manifest callable 只被调用一次（mock 计数断言）；③缺 manifest 属性→warning reason=missing-manifest 且 commands/formats 均空；④manifest 是缺字段/多字段/类型错的 dict→manifest-error；⑤api_version="2.0"→incompatible-api；**api_version 兼容矩阵（#round8-3）**："1.5" 加载成功、"1.0" 加载成功、"2.0" 跳过、"v1"/"abc" 不可解析→incompatible-api；⑥id 非法字符（如 "Bad Id"）→manifest-error。
  - 发现纪律重申：entry_points 只用于第三方插件；内置 8 命令由 app.py 显式注册，发现器返回为空时核心行为与无插件完全一致。
  - 安全文档：插件=同进程全信任 Python（R9）；README/ADR-003 明示"安装第三方插件=信任其作者"，permissions 字段阶段 0 仅声明不强制；NF-07 的沙箱只约束未来 Agent 生成代码，不约束插件。
  - Must NOT do：不做插件沙箱/签名/权限强制执行；不做插件市场/远程下载；不引入 plugy 第三方框架（标准库 entry_points 足够）；示例插件不允许进主 `mycad` 包的默认安装；不碰 MCP server 实现。
  Parallelization: Wave 6（单波；loader 接线要改 T7 产出的 app.py，禁止与 T7 同波）| Blocked by: T3（registry/spec）, T6（signals/bus/handler 契约）, T7（app.py 组合根）| Blocks: T10（CLI `plugins` 子命令）| 并行：无
  References:
  - ledger A13（entry_points + manifest 契约）、A14（MCP 只出 ADR）、A15/A16（PLM/CAE 经信号+元数据+NamedGroup 落缝）、E3（MCP 无会话/句柄）、R9（插件信任）、R10
  - `docs/技术路线.md:30-38`（注册式扩展原则）、`docs/UI设计初稿.md:207-213`（register_left_item 扩展约定；阶段 0 只做后端等价物）
  - Python 标准库文档 importlib.metadata（entry_points/EntryPoint.load）；无需网络
  - ADR-003/ADR-004（T4）
  Acceptance criteria:
  - `uv run pytest tests/plugins -q` 全绿：demo 插件可发现并执行 demo.ping；future api 插件被跳过且 warnings 含其 id；坏插件异常被捕获；冲突 id 跳过；信号回调异常隔离；确定性加载顺序（两次 build_app 列表一致）。
  - **demo 插件的可安装性/可发现性测试纪律（#round9-6，二选一中固定为"不改全局 CI"）**：**T1 写死的 `.github/workflows/ci.yml` 保持不变**（T1 `tests/test_ci_workflow.py` 锁定其文本，本 todo 不得向 ci.yml 添加任何 `uv pip install -e plugins_examples/...` 步骤，也不改 test_ci_workflow 断言）；demo 插件的安装验证改在 **`tests/plugins/test_demo_installed.py`** 内完成：测试用 `subprocess` 在 pytest 的**当前解释器（路径唯一，#round11-NB6：固定 `sys.executable -m pip install -e <repo>/plugins_examples/mycad_plugin_demo` 安装到 CI job 的 uv venv 当前环境，删除"临时 venv"备选——CI 每 job 本就是干净 venv，确定性由 CI 环境保证；路径经 `pyproject.toml` 位置相对定位）**，安装后在**子进程**中 `build_app()` 断言发现 demo、`resolve(x.txt)` 返回 `isinstance(..., FormatPort)` 且 `.write(kernel, path)` 实写摘要文件，测试结束（fixture teardown）`sys.executable -m pip uninstall -y` 恢复环境；该测试在三个 CI job 上随默认 `pytest -q` 自然运行（Windows job 同样覆盖纯 Python 插件可装），无需 CI yaml 任何特例步骤；editable 安装失败/卸载残留都算测试失败。
  - 核心包在未安装任何插件时 `uv run pytest -q` 全绿且无 entry-point 扫描副作用（sys.path 无插件目录时警告列表为空）。
  QA scenarios:
  - happy：editable 安装 demo 插件 → build_app → 执行 demo.ping → 断言输出；`.omo/evidence/task-9-phase0-mvp.md` 记录 `plugins list` 等价输出。
  - failure：安装 future+坏插件夹具 → 断言核心命令仍全部可用、warnings 计数=2、id 正确；卸载插件后发现列表恢复为空；附证据。
  Commit: Y | `feat(plugins): entry-point discovery with manifest/api gating, isolated failures, demo plugin`

- [ ] 10. T10 CLI：REPL + 脚本执行 + 文本/JSON 等价 + 退出码
  What to do / Must NOT do:
  - console script `mycad = mycad.cli.__main__:main`（pyproject [project.scripts]）；子命令：
    - 无参数/`mycad repl`：交互式 REPL（stdin tty 提示符 `mycad> `；非 tty 时从 stdin 读行，等价脚本模式）；
    - `mycad run <file.txt>`：执行 ASCII 命令脚本（`#` 注释/空行跳过）；`mycad run --json <file.json>`：执行存档外的**计划 JSON**，文件 schema、affected_object 映射、隐式 new、执行顺序、outputs 默认命名规则全部以**附录 B（B.1/B.2/B.3）为唯一权威规范**（Plan 状态机 draft→confirmed，记录 confirmed_by="cli-local"，steps 一次 execute_batch，成功后写 metadata 并按 outputs 导出 step/stl/.mc.json）；
    - `new`、`open <path>`、`save [path]`、`export <path>`（按扩展名选 provider）、`meta <key>=<value>`（**CLI 内建文档命令，#6 文本路径元数据唯一入口**：直接调 `Document.set_metadata`，不经过 grammar/Bus、不进命令历史、不参与重放；key 必须 ∈ part_no/revision/material/source/part_name/notes 六白名单——未知键 ValidationError 退出码 1，value 为去引号字符串；脚本与 REPL 均可用；`new` 后 metadata 初值 part_no/revision/material=""、source="local"，故无 meta 行的脚本也能存档）、`undo [n]`、`redo [n]`、`history [--json]`、`validate <file>`（只校验不执行）、`commands [--json]`（列注册表）、`plugins`（列已发现插件与跳过 warning）、`help`、`quit/exit`。
  - 每条建模行走 grammar.parse_line → bus.execute（Bus 内部 validate→normalize→handle，confirmed_by="cli-local"，见 T6 权威规则）；脚本模式默认**逐命令自动提交**（非批）；`begin-batch`/`end-batch` 包裹的段落：end-batch 时用累积行构造 `Plan(steps=[PlannedCommand(...)])`（affected_object 查 B.2 表）→ `plan.confirm(actor="cli-local")` → `bus.execute_batch(plan)`（失败整体回滚，退出码语义见下；批内每条历史 confirmed_by 必须="cli-local"，由 `history --json` 断言）；法兰验收脚本用 batch 包裹 3 条建模命令以验证 F-AGT-04 等价回滚。
  - **文本 ⇄ JSON 等价**：`history --json` 输出的每条命令可被 `to_cli` 还原成脚本行；测试做双向闭环（脚本→执行→history json→to_cli 文本→与原文规范化后相等）。
  - 退出码契约（权威，无第三种归类）：**0 成功；2 用法错误=CLI 层错误**（未知**子命令**、子命令参数缺失/格式错、`run`/`open` 的文件不存在——发生在校验任何建模命令之前）；**1 运行错误=进入建模/计划/批执行后的错误**（未知**建模命令 id**、参数 ValidationError、几何错误、坏 JSON 计划解析失败、BatchRollbackError）；批失败固定=1 且 stdout 打印回滚的命令 ordinal 列表，stderr 单行含 failed_ordinal/failed_command_id。
  - CLI 是顶层组合根之一：**扩展名 provider 解析只用于 `export`**（经 AppServices 的 FormatProviderRegistry/T6 FormatResolver；解析失败 UnknownFormatError 属"运行错误"=退出码 1，扩展名本身是合法 CLI 参数不是用法错误）；**`open <path>` 固定走 `core.open_document`（存档加载器），绝不经过 FormatProviderRegistry**——扩展名必须是 `.mc.json`，否则在 CLI 层按用法错误拒绝（退出码 2，stderr `open only supports .mc.json archives`），不存在"open 其他扩展名经 provider 解析"的路径；测试：`open x.step`/`x.txt`→2 且 registry.resolve 未被调用（spy 断言）、`open x.mc.json`→走 open_document。
  - **权威 CLI 语义表（用户可见契约，全部写死，执行者零发明空间）**：
    - `save [path]`：给路径则存该路径（父目录不存在不创建，OSError 透传=退出码 1；扩展名固定 `.mc.json`，扩展名不是 .mc.json→用法错误 2）；**省略路径规则**：当前文档已有关联存档路径（open 打开或前次 save 过）则覆写该路径；无关联路径（new 后从未 save）又省略路径→用法错误退出码 2，stderr 提示 `save requires a path for an unsaved document`。成功 stdout 打印保存路径。
    - `validate <file>`：**按扩展名判定目标类型**（.json=计划文件，按附录 B.1+命令 schema+B.2 映射校验；.txt=命令脚本，逐行走 grammar.parse_line + schema 校验，不执行）；**.txt 计数口径与批结构规则写死（#round9-NB-D）**：N 只统计通过校验的**建模命令行**（id ∈ 注册表，即 8 内置+已发现插件命令）；`new`/`meta`/`begin-batch`/`end-batch`/`export`/`save`/`open`/`history`/`validate`/`commands`/`plugins`/`help`/`quit` 等 CLI 内建行不计入 N（但仍逐行做语法检查）；注释/空行跳过；批结构复用与执行路径**同一个**批校验函数——未 begin 遇 end、未闭合（EOF 无 end-batch）、嵌套 begin 均按 CliSyntaxError 报出（validate 只报错不执行，退出码归类与 run 执行时相同=2）；合法→退出码 0、stdout `valid: <type> N step(s)`（<type> 为 `plan` 或 `script`）；非法→退出码 1（建模参数/批内容的校验失败=运行错误归类，含首个错误点路径；批结构错误=2）；文件不存在→2；其他扩展名→2；validate 不改变任何文档状态（独立临时校验上下文）。
    - `history [--json]`：无 `--json` 时每命令一行，格式固定 `<ordinal>: <id> <to_cli(params)>  [confirmed_by=<actor>]`（confirmed_by 为空时省略方括号段）；**`history --json` 输出固定 JSON 对象**：`{"commands":[{"ordinal":int,"id":str,"version":int,"params":{...},"timestamp_utc":str,"confirmed_by":str|null,"amendments":[{"at":str,"actor":str,"from_params":{...},"reason":str}]}]}`——命令对象七键（amendments 仅非空时出现，与存档格式一致；**timestamp_utc 故意包含**：history 是审计视图，字段集与存档命令元素对齐）；顶层键恰好 `commands`（additionalProperties 纪律：测试断言键集）；按 ordinal 升序；该视图只含已执行**建模**命令（new/meta/begin-batch/end-batch/export/save/history/validate/commands/plugins/help/quit 不出现——快照比较的权威对象=规范化后的建模命令历史）。
    - `plugins`（无参）：stdout 每行一个已加载插件 `loaded: <id> v<version> api=<api_version> commands=<n> formats=<n>`；被跳过的插件每行 `skipped: <distribution-name> reason=<code>`，其中 `<code>` 必须逐字取自 T7 `mycad.plugins.types.WARNING_REASONS` 六值之一（`missing-manifest|manifest-error|incompatible-api|command-conflict|provider-conflict|load-error`，#round9-5：T10 不另立原因集合）；退出码恒 0（跳过不构成错误）；格式在 T9 测试中快照锁定，快照对 reason 集合做 `typing.get_args(WARNING_REASON)` 派生断言而非手写列表。
    - `commands [--json]`（#NB4 输出契约）：无 `--json` 时每条命令一行，格式固定为 **制表符分隔三列** `<verb_aliases[0]>\t<id>\t<summary_en>`，按 verb 字典序升序；`--json` 时输出 `{"commands":[{"verb":str,"id":str,"summary_en":str,"label_zh":str}, ...]}`（恰好四键，按 verb 升序，label_zh 随附为阶段 1 UI 预留数据）；顶层键恰好 `commands`；退出码恒 0。无插件时恰好 8 行/8 元素（该计数与 id 集合作快照测试）。**计数测试的环境隔离写死**：在禁用 entry-point 发现的进程/monkeypatch 环境中运行（`build_app(discoverers=[])` 或 monkeypatch entry_points 返回空，确保即使 CI 以 editable 方式装了 mycad_plugin_demo，"恰好 8"仍成立）；另设一例装了 demo 插件的环境断言为 9 行且多出 demo.ping（两例显式区分"无插件环境/有插件环境"，禁止按当前环境隐式断言）。
    - `meta <key>=<value>`：成功 stdout 回显 `<key>=<value>`、退出码 0；未知 key（白名单外）→ ValidationError 退出码 1（与建模参数校验同级=运行错误）；缺少 `=`/无参数→用法错误 2；脚本模式连续 4 条 `meta part_no=...` 后 `save`，存档 metadata 四必填键非空（`examples/flange_script.txt` 即此路径）。
  - 平台纪律：pathlib 处理路径；stdin/stdout/stderr 全部 UTF-8（Windows 下 `sys.stdout.reconfigure(encoding="utf-8")` 兜底，Python 3.12 通常已 UTF-8 mode——加测试覆盖中文路径与中文 metadata 值 round-trip）；不用 curses/readline 之外的东西（readline 可选导入，Windows 缺失时静默降级）。
  - 测试 `tests/cli/`：用 pytest + capsys/tmp_path 覆盖每个子命令；REPL 用喂多行 stdin（含错误行后继续执行、quit）；退出码两档（0 成功/1 运行/2 用法）穷举矩阵：2 档至少——未知子命令=2、`open` 不存在文件=2、缺少必填子命令参数=2；未知建模命令 id=1、参数校验失败=1、损坏 JSON=1、批回滚=1；批回滚端到端；JSON 计划执行（含附录 B.3 全部失败用例：缺 metadata/未知顶层键/未知 metadata 键/affected_object 不匹配/空 steps=1，计划文件不存在=2，outputs 缺省命名与部分声明）；Windows CI job 必跑同一套用例。
  - **批结构失败矩阵（CliSyntaxError，退出码 2，在任何建模命令校验之前判定）**：①未 `begin-batch` 遇 `end-batch`；②`begin-batch` 后到文件尾/stdin EOF/`quit` 仍无 `end-batch`（未闭合批：报错且**不执行**批中任何行）；③嵌套 `begin-batch`（已有活动批时再 begin）；三类各 REPL 与脚本模式一例，断言退出码 2、stderr 单行错误码、历史为空（未闭合/嵌套场景批内行均不入历史）。
  - Must NOT do：不做彩色/tUI/自动补全（阶段 1 UI 的事）；不做网络；不内置自然语言；不在 CLI 绕过确认语义（本地 CLI=用户本人：所有 CLI 建模路径必须落 `confirmed_by="cli-local"` 审计字段——普通行直接随 execute 落、批/`run --json` 经 Plan+confirm+execute_batch 落，禁止产生 null）；不把视图类命令（view.*）注册进来（无 UI）。
  Parallelization: Wave 7（单波）| Blocked by: T7（8 命令）, T8（export/open）, T9（plugins 子命令）| Blocks: T11 | 并行：无
  References:
  - `docs/需求分析书.md:101-110`（F-AGT-05 CLI 等价命令）、`:136-149`（确认流；视图类例外不适用 headless）、NF-03 可审计
  - `docs/技术路线.md:155-160`（CLI 语法/校验器）、ledger A10（ASCII 英文 CLI）、E8（修错循环不适用——无 LLM）
  - T3 grammar、T6 bus/plan/persistence、T8 providers、T9 discovery 的实际接口
  Acceptance criteria:
  - `uv run mycad commands` 列出 8 条（+插件 demo 时 9 条）；`uv run mycad run examples/flange_script.txt`（examples 在 T11 落地；本 todo 先用测试夹具）退出码 0 并导出 STEP/STL；批失败夹具退出码 1 且历史回滚断言通过。
  - `uv run pytest tests/cli -q` 全绿（三个 CI job：ubuntu-22.04/24.04/windows-latest）；basedpyright/ruff 绿。
  QA scenarios:
  - happy：stdin 喂入 new → begin-batch → cylinder(new)/hole/hole-pattern 三条（与 examples 同路径，孔只走 feature.hole/hole-pattern，不出现 cut）→ end-batch → export step/stl → history --json → undo 3 全序列，断言体积=36794.3331588437（math 直算）与批回滚到空文档，输出存 `.omo/evidence/task-10-phase0-mvp.md`。
  - failure：未知子命令→2；`open` 不存在路径→2；脚本中第 2 条建模参数非法→批回滚退出 1；未知建模 id 行→1；损坏 JSON 计划→1（不是 traceback，是单行错误消息）；各类 stderr 文案与退出码附证据。
  Commit: Y | `feat(cli): repl and script runner with batch transactions, json equivalence, exit-code contract`

- [ ] 11. T11 法兰验收资产 + examples + NOTICE/README 收尾 + Windows/编码用例
  What to do / Must NOT do:
  - `tests/golden/flange_golden.json`（固定路径，无 assets 备选；**JSON 不支持注释**：公式以 `"_formula"` 键逐组记录，加载器断言其存在但不参与几何比较，未知键忽略纪律在测试注释中写明）：**两组 golden 参数表**，每组字段 od_mm/bore_mm/thk_mm/hole_d_mm/hole_count/hole_pcd_radius_mm/expected_volume_mm3/bbox_size/cylindrical_faces：
    - Group A：OD80、bore20、thk8、4×d6@R25；**expected_volume_mm3 = 36794.3331588437**（真值 36794.333158843656…），`_formula = "math.pi*8*(40**2-10**2-4*3**2)"`；bbox size=[80,80,8] 居中；solid_count=1；cylindrical_faces=6；
    - Group B：OD100、bore30、thk10、6×d8@R35；**expected_volume_mm3 = 68455.3039217216**（真值=π·10·(50²−15²−6·4²)=21790π=68455.30392172163…），`_formula = "math.pi*10*(50**2-15**2-6*4**2)"`；bbox size=[100,100,10]；solid_count=1；cylindrical_faces=8；
    - 每组测试内**直接按该组尺寸用 math.pi 现算期望值**，断言现算值与 JSON 常量之差 <1e-9、实测体积与现算值之差 <1e-6；**禁止从实现输出反录、禁止书写 36794.3332 四位小数常量**。
  - `examples/flange_script.txt` 与 `examples/flange_plan.json` 均为**手工编写**（禁止任何生成器反录），被验收测试直接引用。脚本序列（ASCII）：new → `meta part_no=FLANGE-DEMO-001` → `meta revision=A` → `meta material=Q235` → `meta source=example`（四条 meta 使存档 metadata 与计划 JSON 一致；不进命令历史）→ begin-batch → `cylinder radius=40 height=8 center=[0,0,0] mode=new`（#round11-5：键序=schema properties 序 radius/height/center/mode，center 为 default 填充键的显式形态，与 to_cli 全键输出规则逐行一致） → `hole target_face.surface=plane target_face.axis=+Z target_face.rank=0 position.kind=center diameter=20 depth.kind=through_all`（中心孔，feature.hole 谓词路径）→ `hole-pattern base_hole.target_face.surface=plane base_hole.target_face.axis=+Z base_hole.target_face.rank=0 base_hole.position.kind=center base_hole.diameter=6 base_hole.depth.kind=through_all pattern.kind=polar pattern.radius=25 pattern.count=4 pattern.start_angle_deg=0`（4 均布孔）→ end-batch → export flange.step → export flange.stl → save flange.mc.json → history --json。计划 JSON 为等价有序命令，**文件结构严格符合附录 B.1 权威 schema**（顶层 plan_id/metadata/steps，无 outputs 键以走 B.3 默认命名；每个 step 含 id/version/params/affected_object 四键，affected_object 逐字取 B.2 映射），metadata 填 part_no="FLANGE-DEMO-001"、revision="A"、material="Q235"、source="example"。两者必须产出同一 golden 几何（参数化等价测试）。
  - `tests/test_acceptance_flange.py`（需求书 §8 在阶段 0 的可自动化投影；UI 相关条目 #4 显式 skip 并注明阶段 1）：
    1. 参数可改（真正的参数化重放，**Group B 的唯一验收途径**，避免与下面 #1b 重复实现）：先对 **Group A 跑一次完整建模序列**（与 examples/flange_script.txt 同构）断言首组体积=36794.3331588437；**然后在同一个 Document 上**经 `bus.edit_and_replay(ordinal, new_params, actor="acceptance-test", reason=...)` 把 OD/bore/thk/孔径/孔数/PCD 六类参数至少各改 1 次改到 Group B 对应值，断言体积=68455.3039217216；**断言方式=同一 Document 改已执行命令 params 后整体重放，不是新建文档、不是重新跑脚本、不为 Group B 再写第二份完整序列脚本**；验证谓词选择器在不同孔径/PCD 下仍选中同一语义面组（无 TopologyReferenceError），且被改命令的 ordinal/timestamp_utc 不变、amendments 追加、from_params 正确；
    1b. golden JSON 中 Group B 常量（68455.3039217216）仅用于与上面 edit_and_replay 终态体积比对及公式自洽断言（常量−math 直算差 <1e-9），**不为 Group B 建独立 examples/完整序列**；
    2. 计划→确认→执行：用 Plan 状态机（confirmed_by="acceptance-test"）execute_batch 后导出 STEP，文件>10KB 且可 re-import、体积一致；5 个孔全部经 feature.hole/hole_pattern 谓词路径（history 中无 modify.boolean_cut 节点用于孔）；
    3. 批撤销：**在同一个持久 REPL 会话/fixture 内**（`run` 进程结束即释放独立文档，进程外无法 undo——禁止写成 `run script.txt` 后再 `undo` 的跨进程序列）执行 examples 的三条建模命令（begin-batch→cylinder/hole/hole-pattern→end-batch），随后 `undo 3`（阶段 0 undo 粒度=命令，等价删批）后体积回到批前（空文档 solid_count=0）；CLI/history 中可见等价英文命令（文本快照断言，**比较对象=规范化后的已执行建模命令**：排除 new/meta/begin-batch/end-batch/export/save/history 等非建模行；to_cli 规范化后与 examples 中建模行逐行一致）；
    4. UI 布局条目：pytest.skip("phase 1: PySide6 shell")；
    5. LICENSE/NOTICE 存在且 README 声明 Apache-2.0（现有 README 已有许可，核对不改坏）。
  - 平台/编码用例：中文路径（`tmp_path/"法兰目录"/"法兰.step"`，ubuntu+windows CI 双跑）；中文 metadata 值存档往返 UTF-8 不丢字；`PYTHONUTF8=0` 场景在 Windows job 显式验证 stdout 仍 UTF-8（reconfigure 兜底测试）；路径全部 pathlib（grep 守卫：src 中不出现硬编码 `/` 拼接路径与 `os.sep` 假设的新增代码）。
  - **`tests/test_scope_audit.py`（F2/F4 机器化审计的唯一实现，Final wave 直接运行，禁止人工 grep 替代）**，四组测试，全部只用标准库 ast/json/subprocess/pathlib：
    1. `test_no_forbidden_imports`：AST 扫描 `src/**/*.py` 全部 import，违禁根模块集合=PySide6/PyQt6/PyQt5/vtk/mcp/cadquery/OCC/packaging/urllib/requests/http/socket/restrictedpython；命中即失败并打印文件:行号:模块名。白名单：build123d/OCP/numpy 仅允许在 `src/mycad/geom/` 内出现（逐节点比对文件路径前缀），geom 外任何一处即失败。
    2. `test_no_out_of_scope_code`：断言不存在 `view.`/`sketch.`/`datum.` 命令 id（扫注册表与 builtin_commands）；不存在 schema_tools/schema_catalog/tool_schema 模块文件与 `tests/snapshots/` 目录；`src/` 内 grep 无 `document.import_step`/`imported_solid`/`ImportSourceMissingError` 标识符；STEP 读 API 的唯一出现位置白名单=`tests/helpers/step_roundtrip.py`（src 中零出现）；无 jt/parasolid/acis/sat/x_t/sldprt/nx/catia 商业格式适配模块（大小写不敏感匹配文件名与字符串字面量）。
    3. `test_runtime_closure_clean`：subprocess 跑 `uv tree --package mycad --no-dev`（全计划唯一命令字面量，与 F4 一致），解析输出断言闭包不含 PySide6/vtk/mcp/cadquery/pythonocc 分包；同时断言 build123d/cadquery-ocp-novtk 在闭包内（正向防 pin 误删）。
    4. `test_tree_boundaries`：读 pyproject 打包配置断言 `plugins_examples/`、`tests/fixtures/` 不在 wheel 包含集；subprocess `git ls-files docs/` 与基线三份文件 hash 对比（基线 hash 列表读取 T1 生成的 `tests/fixtures/baseline_doc_sha256.json` fixture（#round11-NB4：fixture 是唯一来源，测试内禁止手写第二份常量——T11 只消费该 fixture，若 T1 未生成则回 T1 补））断言 docs/ 三份基线零改动；断言仓库根（排除 .git/.omo/.venv）无 review/island 目录与 `*-ledger.md` 规划临时物。
    每组至少一个反向自证：用 tmp_path 生成一个含违禁 import 的临时 .py 走同一扫描函数必须被判失败（测试的是审计函数本身有效，而非只测现状通过）。
  - NOTICE：补第三方归属段，**覆盖锁定环境中的全部运行时依赖而非仅 5 个大件**：以 **`uv tree --package mycad --no-dev`**（固定命令；`--no-dev` 防止 pytest/ruff 等开发依赖混入闭包；或等价 `uv pip list --python .venv` 后按 pyproject 运行时声明过滤）枚举运行时闭包，逐个读 site-packages 的 LICENSE*/METADATA `License` 字段程序化核对；五个大件的固定预期=build123d (Apache-2.0)、cadquery-ocp-novtk / OCCT (**以 METADATA 程序化核对结果为准，预期为 LGPL 系列——测试不得在 NOTICE 中手写死 "LGPL-2.1-or-later"，实测许可证字符串与预期族不符即测试失败回修**；另注明 wheel 为独立原生库/动态加载边界事实)、numpy/scipy/scikit-learn (BSD)、ezdxf (MIT)、lib3mf (BSD-2-Clause)；其余小包（anytree/ocpsvg/ocp_gordon/trianglesolver/sympy/webcolors/requests 等）按实际 METADATA 列名+许可证，**禁止"待核实/TBD/未知"等占位文本进入可交付 NOTICE（#round8-NB3，fail-closed）：METADATA 缺 License 字段或解析不出 SPDX 标识时，`tests/test_notice.py` 直接失败，执行者必须去该分发包的 LICENSE 文件取证据（把许可证全名+证据文件相对路径写进 NOTICE 与 `.omo/evidence/task-11-phase0-mvp.md`）后重跑，严禁编造也严禁留空占位**。**断言纪律（脚本化，非人工 grep）**：`tests/test_notice.py` 固定断言 NOTICE 含五个大件归属名与项目 LICENSE 为 Apache-2.0，另做"uv tree 运行时闭包每个分发名在 NOTICE 中均出现"的程序化比对（闭包名单来自测试时实际环境，不手写）；某条许可证与预期不符或闭包中存在 NOTICE 未列名 → 测试失败回 T1/T4 修正，不得放宽断言；`tests/test_notice.py` 另扫 NOTICE 文本不得包含 `待核实`/`TBD`/`未知`/`unknown license` 占位串（#round8-NB3 fail-closed）。
  - README：增补"阶段 0 能力/快速开始（三条命令跑通法兰）/平台支持矩阵（T1 支持、T2 预期 glibc≥2.31、T3 评估中）/插件与 MCP 路标（指向 ADR）"；不删现有内容。
  - Must NOT do：不造测试数据反录 golden；不 skip 非 UI 的验收条目；不在本 todo 补做新功能（发现缺口=回 T7/T8/T10 修，不走验收 todo 塞代码）；不承诺信创认证/安装包；不引入新依赖。
  Parallelization: Wave 8（单波，末波）| Blocked by: T10（端到端）、T1 全程 CI | Blocks: Final verification wave
  References:
  - `docs/需求分析书.md:164-172`（§8 五条验收基线，逐条映射见上）
  - 尖刺真值：/tmp/opencode/mycad-spike/flange_spike.py:27-59（面数/文件大小/往返；体积打印 36794.3332 是 4 位舍入，解析真值见 golden 纪律）；E11
  - ledger A9/A10/A18、R13/R18；`docs/技术路线.md:176-180`（第三方合规）
  Acceptance criteria:
  - `uv run pytest -q` 全绿（ubuntu 两 job 必绿；Windows job 有远端时必绿，**无远端时声明为"就绪未实测"遗留、不得声称多平台已验证**），其中 `tests/test_scope_audit.py` 四组测试+反向自证全绿（F2/F4 只接受该文件输出）；
  - T1 已提供基线文档 hash fixture `tests/fixtures/baseline_doc_sha256.json`（#round11-NB4：T1 生成的该 fixture 是唯一来源，test_tree_boundaries 读取之，不得在测试内手写常量；若缺失则本 todo 失败回 T1，不得在 T11 私造常量）。`uv run mycad run examples/flange_script.txt` 与 `uv run mycad run --json examples/flange_plan.json` 均退出码 0，产出 step/stl/mc.json，几何断言同 golden；生成的 STEP 经 `tests/helpers` 读回 1 solid 体积一致。
  - **#round10-2 产物清理固化**：端到端运行的工作目录固定为 pytest `tmp_path`（测试内运行）与 F3 手动 QA 的临时克隆；任何在仓库工作树（仓库根或 `examples/`）产生的六个验收产物，证据采集后必须且只需执行一条固定清理命令：`rm -f flange.step flange.stl flange.mc.json examples/flange_plan.step examples/flange_plan.stl examples/flange_plan.mc.json`（命令字面量写入 F3 操作步骤）。这些路径同时已被 T1 `.gitignore` 逐行忽略，故 F4 的 `git status --porcelain` 干净断言无论清理是否执行都成立；T11 新增测试：在临时 git 工作树中 touch 六个路径后 `git status --porcelain` 必须为空（验证 .gitignore 规则真实生效，反向自证：touch 一个未忽略文件必须出现）。
  - 在同一持久 REPL fixture 内 `undo 3`（或批撤销等价；不得跨 `run` 进程）后 history 为空、solid_count=0（空文档 mass_properties 语义见 T2）；history 文本快照与 examples 的**建模行**（排除 meta/批结构/export/save/history 非建模行）逐行一致。
  - NOTICE 含 build123d/OCCT/numpy/ezdxf/lib3mf 五个大件归属名**且运行时依赖闭包每个分发名都被列出**（`tests/test_notice.py` 程序化比对 uv tree 闭包）；README 含 "Apache" 与平台矩阵三节标题。
  QA scenarios:
  - happy：全新 clone 视角执行 README 三条快速开始命令（uv sync → uv run mycad run examples/flange_script.txt → 检查产物），全过；把终端完整输出与 `ls -l` 产物清单、golden 断言结果存 `.omo/evidence/task-11-phase0-mvp.md`；Windows job 的同运行日志附 run URL。
  - failure：故意把 golden volume 改 ±0.5 → 参数化测试必须红并显示解析公式期望值；删 LICENSE → 合规测试红；两验证后还原。端到端批中插一条坏命令 → 回滚后无产物半成品（step/stl 未写出或保留旧文件——export 在批外，断言语义）。
  Commit: Y | `test(acceptance): flange golden, bilingual-path encoding cases, examples, NOTICE attributions`

## Final verification wave
> T11 完成后并行执行；四项全部 APPROVE 才可交付。每项产出书面结论到 `.omo/evidence/final-<N>-phase0-mvp.md`；任一 FAIL → 回对应 todo 修复 → 重跑该波，不得带病交付。

- [ ] F1. Plan compliance audit（oracle 只读代理）
  - 逐条核对 Must have 10 项与 T1–T11 的覆盖映射；8 个命令 id 与 `docs/UI设计初稿.md:160-185` 逐字比对；ADR-001…006 存在且与计划决策一致；`.omo/drafts/phase0-mvp-research-ledger.md` 的 A1–A20 每条要么落地、要么在 ADR/Out 中显式处置；R1–R18 每条有缓解或显式接受记录。
  - 证据：覆盖矩阵表（需求/决策 → 文件/测试 → 结果）。

- [ ] F2. Code quality review（oracle 只读代理）
  - 全新环境视角：`uv sync --frozen` 后四条质量门（ruff check / ruff format --check / basedpyright strict / pytest）全绿且无被豁免项；零 `# type: ignore`（tests/typing/ 对照文件除外）、零 `Any` 逃逸、零空 except；layering 守卫测试存在且有效（临时反向注入必须变红的现场验证）；公开 API docstring 完整；模块依赖方向无环（core 不依赖 geom/cli；geom 仅依赖 core 的中立类型与 exceptions）。
  - **机器化门（不接受人工 grep 转述）**：`uv run pytest tests/test_layering.py tests/test_scope_audit.py -q` 必须全绿；评审现场对每个守卫各做一次反向注入（新增一条违禁 import / 一个违禁依赖）确认测试变红后回退。
  - 证据：质量门输出 + 反向注入验证记录（含变红/回退两次终端输出）。

- [ ] F3. Real manual QA（unspecified-high 代理，必须真实运行，不接受日志转述）
  - 在干净 venv 中按 README 快速开始从零执行：`uv sync`（含国内镜像指令至少演练一次）→ `uv run mycad run examples/flange_script.txt` → `uv run mycad run --json examples/flange_plan.json`；用产物经 `tests/helpers` STEP 读回复验体积/面数（或运行 pytest 往返用例现场观察）；REPL 交互走 new→建模→undo→redo→save→open→export；故意批失败观察回滚与退出码；三个 CI job 实际 run 链接/日志逐行核对（含中文路径用例）；**若交付时仍无 GitHub 远端，F3 结论必须写明"Windows 就绪未实测"为已知遗留，APPROVE 结论不得声称多平台已验证**（无缩写代号）。
  - 证据：完整终端会话记录、产物字节数/体积、CI URL。

- [ ] F4. Scope fidelity（oracle 只读代理）
  - 对照 Must NOT have 清单逐项审计，**全部以 `uv run pytest tests/test_scope_audit.py -q` 机器化执行，不接受人工 grep 结论**。该测试文件（T11 交付，规范见 T11）程序化断言：
    1. **import/依赖闭包**：用 AST 扫描 `src/`，无 `PySide6`/`PyQt6`/`vtk`/`mcp`/`cadquery`/`OCC`(pythonocc)/`packaging`/`restrictedpython` 等违禁模块 import（#round10-NB4：禁词集合与 T11 `tests/test_scope_audit.py::FORBIDDEN_IMPORT_ROOTS` 为同一字面量来源，F4 复核者直接引用该常量，禁止在 F4 另写拼写变体；匹配大小写不敏感，真实 PyPI 包名为 RestrictedPython）；**build123d/OCP/numpy 三者权威规则一致：只允许出现在 `src/mycad/geom/` 包内，core（含中立 DTO，DTO 只用标准库 tuple/float）及任何其他包零例外**；`uv tree --package mycad --no-dev`（命令字面量全计划唯一，测试内以 subprocess 执行后文本解析；不再使用 --json 变体）输出闭包中不含上述违禁分发包名（断言运行时闭包子集，dev 依赖不计入）。
    2. **越界命令/代码**：无 `view.`/`sketch.`/`datum.` 命令 id 注册；无 `schema_tools`/`schema_catalog`/`tool_schema` 模块与 `tests/snapshots/`；src 中无 STEP 读产品路径（读 API 仅允许 `tests/helpers/step_roundtrip.py`，白名单断言）、无 `document.import_step`/`imported_solid`/`ImportSourceMissingError` 标识符；无商业格式（jt/parasolid/acis/sat/x_t/sldprt/nx/catia）适配代码。
    3. **发行/网络边界**：无安装包配置文件（AppImage/flatpak/msi/nsis 相关打包脚本与 PyInstaller spec）；src 中无 `urllib`/`requests`/`http`/`socket` 网络 import（白名单：无，即全部禁止）。
    4. **树边界**：`plugins_examples/` 与 `tests/fixtures/plugins/` 不被任何 `packages.find`/wheel 打包配置包含（读 pyproject 打包配置断言）；`git status --porcelain` 干净状态下 `git diff` 核对 docs/ 三份基线原文零改动；产品树（仓库根，排除 .omo/、.git/）无规划临时物（断言不存在 `.omo` 外的 `review/`、`island/`、`*-ledger.md` 等规划文件）。
  - 每条断言失败信息必须打印命中文件与具体违禁项，便于回修；F4 评审者只复核该测试的禁词清单与 Must NOT 清单逐条对应（覆盖性核对）+ 附一次真实运行输出。
  - 证据：`pytest tests/test_scope_audit.py -v` 完整输出 + `uv tree --package mycad --no-dev` 输出 + `git diff --stat`（基线文档零改动）。

## Commit strategy

- 每个 todo = 1 个（必要时同 todo 内最多 2 个）语义提交，提交信息 Conventional Commits（与各 todo Commit 行一致）；Implementation+Test 同提交，不分离。
- T1 首先建立初始提交序列：①`chore: import baseline docs, LICENSE, NOTICE, README`（现状快照）②T1 工程骨架提交。`.omo/plans|drafts` 与 evidence 说明在 T1 同提交入库（规划透明可审计）。
- 提交前本地四条质量门必须全绿；失败提交不允许靠后续提交修补（amend 当次提交）。
- 无远端时全程本地提交；配置 GitHub 远端后**默认在单一分支 `phase0-mvp` 上工作、最终单 PR 合入 main**（固化为默认，用户可显式覆盖改策略）；CI 三个 job（ubuntu-22.04/24.04、windows-latest）全绿才允许合并/进入 Final wave；禁止 main 直推。
- 不打 tag、不发 release（阶段 0 内部里程碑；安装包与发行是 Out）。

## Success criteria

阶段 0 验收通过当且仅当：

1. **法兰端到端**（需求书 §8 的 headless 投影）：`mycad run examples/flange_script.txt` 与 `mycad run --json examples/flange_plan.json` 两条等价路径均退出码 0，产出 Group A 的 STEP（>10KB，经测试辅助读回 1 solid、体积等于 math 公式真值，容差 1e-6 mm³）、STL（>1KB）、.mc.json；**Group A（OD80/bore20/thk8/4×d6@R25=36794.3331588437）经完整建模序列；Group B（OD100/bore30/thk10/6×d8@R35=68455.3039217216）不经独立完整序列，只由同一 Document 的 edit_and_replay 参数化重放验收**（见 T11 验收 #1/#1b，两处以此句为唯一权威，防止重复/冲突实现）。
2. **确认/回滚/改参语义**：批计划经 Plan 恰好 6 边状态机（draft→confirmed 显式动作）执行；批中任一命令失败时几何与历史整体回滚到批前，固定抛 BatchRollbackError 含 failed_ordinal/failed_command_id/reason/executed_ids；`undo`/`redo` 经历史重放正确；**`bus.edit_and_replay` 在同一 Document 改 params 重放正确（Group A→B 六类参数各≥1 次，ordinal/timestamp_utc 不变、amendments 留痕，失败回滚）**；history（文本与 JSON）与日志可审计，文本⇄JSON 双向等价；CLI 退出码 0/1/2 分类正确。
3. **架构缝成立**：无插件环境核心独立可用；api_version 不兼容/损坏/id 冲突插件被跳过且不影响核心；FormatProvider 可按扩展名解析、未知格式显式拒绝；扩展不改动 core 一行（demo 插件证明）。
4. **封层纪律**：build123d/OCP/numpy 不越出 geom 包（AST 守卫测试）；core 可在不加载 OCCT 的情况下 import；所有几何错误以项目异常类型带命令 id 呈现，无 OCP 异常/堆栈穿透。
5. **平台与质量**：CI 三个 job（ubuntu-22.04/ubuntu-24.04/windows-latest）中两个 Ubuntu job 必须绿；windows-latest 有远端时必须绿（无远端则交付物显式标"就绪未实测"遗留，不算失败但不得虚报）；ruff/format/basedpyright strict/pytest 四门零豁免；中文路径与 UTF-8 往返用例通过。
6. **决策留痕**：ADR-001…006 齐备且与实现一致；NOTICE 第三方归属准确；README 快速开始从零可复现（含国内镜像说明）。
7. Final verification wave F1–F4 全部 APPROVE，证据齐备于 `.omo/evidence/`。

阶段 1–3 仅路线图锚点（ADR-003/004/005/006 已埋缝）：阶段 1 PySide6 壳与 Viewport（网格预览起步，R15 双 OCCT 运行时禁律；STEP 产品化导入 F-DOC-03）；阶段 2 Agent 计划确认闭环（工具 schema 按本附录落地生成代码、MCP SDK 锁主版本、确认 token 红线、评测集）；阶段 3 草图约束/特征加深与 T3 龙芯 go/no-go spike。这些**不是**本计划的交付或验收项。

## 附录 A：Command schema catalog（规范，权威字段定义）

> 本附录是 8 条内置命令 `params_schema` 的**唯一权威**：T7 逐字落地为 JSON Schema（T3 校验器支持的 13 项关键字见 T3，含 oneOf/$ref），执行者不得增删改字段名或取值；未来版本号变更必须改本附录。所有长度单位 mm、角度单位十进制度。CLI 动词别名见各命令标注，文法（扁平点键/标量数组）见 T3 grammar 6 例。**A.0 的全部 $defs 即 T7 单一常量表 `COMMAND_SCHEMA_DEFS` 的内容（同名同字段），各命令 schema 仅以 `$ref: "#/$defs/<Name>"` 引用，禁止复制子结构。**

### A.0 共享定义（$defs，被各命令引用）

```json
{
  "FaceSelector": {"oneOf": [
    {"type": "object",
     "required": ["surface", "axis"],
     "additionalProperties": false,
     "properties": {
       "surface": {"const": "plane"},
       "axis":    {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]},
       "rank":    {"type": "integer", "minimum": 0}
     },
     "description": "平面分支：axis 必填且只允许六个带符号轴值（外法向方向）；不允许空串/缺省（schema 层即拒绝，不等到 geom 执行）。rank 可选。"},
    {"type": "object",
     "required": ["surface"],
     "additionalProperties": false,
     "properties": {
       "surface": {"const": "cylinder"},
       "axis":    {"type": "string", "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z", ""]},
       "rank":    {"type": "integer", "minimum": 0}
     },
     "description": "圆柱面分支：axis 可缺省；缺键（经 normalize_params 将空串删除后）=全部圆柱面，给带符号轴则按无向轴向匹配，+Z/-Z 等价。wire 形态绝不写 null（#round9-3/#round10-NB1）。"}
  ],
  "description": "解析语义（权威，见 T2 selectors.py）：plane 缺 axis 在 schema 校验期即 ValidationError（执行前校验契约）；过滤 surface→按 axis 匹配→候选按面积降序、等面积按面心(x,y,z)字典序升序全序排列；rank 给定时取第 rank 个（越界 TopologyReferenceError），省略时候选必须恰好 1 个面，0 或多个均 TopologyReferenceError(no-match/ambiguous)。禁止裸拓扑索引。"},
  "EdgeSelector": {
    "type": "object",
    "required": ["parent_faces"],
    "additionalProperties": false,
    "properties": {
      "parent_faces": {"type": "array", "items": {"$ref": "#/$defs/FaceSelector"}, "minItems": 1},
      "curve": {"type": "string", "enum": ["line", "circle", ""]}
    }
  },
  "Position": {"oneOf": [
    {"type": "object", "properties": {"kind": {"const": "center"}}, "required": ["kind"], "additionalProperties": false}
  ], "description": "v1 仅支持面心；任何其他 kind 必须 ValidationError。"},
  "Depth": {"oneOf": [
    {"type": "object", "properties": {"kind": {"const": "through_all"}}, "required": ["kind"], "additionalProperties": false},
    {"type": "object", "properties": {"kind": {"const": "blind"}, "value": {"type": "number", "exclusiveMinimum": 0.0}}, "required": ["kind", "value"], "additionalProperties": false}
  ]},
  "Pattern": {"oneOf": [
    {"type": "object", "properties": {
      "kind": {"const": "polar"}, "radius": {"type": "number", "exclusiveMinimum": 0.0},
      "count": {"type": "integer", "minimum": 2, "maximum": 64},
      "start_angle_deg": {"type": "number", "default": 0.0}},
      "required": ["kind", "radius", "count"], "additionalProperties": false}
  ], "description": "v1 仅 polar；kind=linear 必须 ValidationError（未实现，不静默接受）。start_angle_deg=0 对应全局 +X 轴，正向为从 +X 朝 +Y（自 +Z 俯视逆时针），角度定义在全局 XY 平面。阶段 0 限制：base_hole.target_face 必须解析为外法向平行全局 Z 的水平面（+Z/-Z，|n·ẑ|≥1−1e-9），否则 geom 执行时固定抛 TopologyReferenceError(reason='pattern-target-not-horizontal')；一般斜面局部坐标系（+X 在面内投影、退化用 +Y）为阶段 1 演进口。"},
  "Profile": {"oneOf": [
    {"type": "object", "properties": {"type": {"const": "circle"}, "radius": {"type": "number", "exclusiveMinimum": 0.0},
      "center": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2, "default": [0.0, 0.0]}},
      "required": ["type", "radius"], "additionalProperties": false},
    {"type": "object", "properties": {"type": {"const": "rect"}, "width": {"type": "number", "exclusiveMinimum": 0.0},
      "height": {"type": "number", "exclusiveMinimum": 0.0},
      "center": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2, "default": [0.0, 0.0]}},
      "required": ["type", "width", "height"], "additionalProperties": false}
  ], "description": "截面位于 XY 工作平面 z=0。"},
  "Mode": {"type": "string", "enum": ["new", "add", "cut"], "default": "new"},
  "Center3": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3, "default": [0.0, 0.0, 0.0]},
  "Positive": {"type": "number", "exclusiveMinimum": 0.0},
  "Tool": {"oneOf": [
    {"type": "object", "properties": {"type": {"const": "box"},
      "size_x": {"$ref": "#/$defs/Positive"}, "size_y": {"$ref": "#/$defs/Positive"}, "size_z": {"$ref": "#/$defs/Positive"},
      "center": {"$ref": "#/$defs/Center3"}},
      "required": ["type", "size_x", "size_y", "size_z"], "additionalProperties": false},
    {"type": "object", "properties": {"type": {"const": "cylinder"},
      "radius": {"$ref": "#/$defs/Positive"}, "height": {"$ref": "#/$defs/Positive"}, "center": {"$ref": "#/$defs/Center3"}},
      "required": ["type", "radius", "height"], "additionalProperties": false}
  ], "description": "仅 modify.boolean_cut 使用；内联工具体，v1 不支持具名引用。"},
  "Hole": {"type": "object",
    "required": ["target_face", "position", "diameter", "depth"],
    "additionalProperties": false,
    "properties": {
      "target_face": {"$ref": "#/$defs/FaceSelector"},
      "position": {"$ref": "#/$defs/Position"},
      "diameter": {"$ref": "#/$defs/Positive"},
      "depth": {"$ref": "#/$defs/Depth"}},
    "description": "#round11-3：feature.hole 全部参数的共享定义；feature.hole 以根级 $ref 引用本定义，feature.hole_pattern.base_hole 以 $ref 复用——消除 T7 “禁止复制子结构”与 base_hole 字段集复用的矛盾；键序取本 properties 声明顺序 target_face/position/diameter/depth。"}
}
```

### A.1 八条命令

1. **`feature.box`** — CLI `box`；version=1；`summary_en="Create a rectangular box"`；`label_zh="长方体"`
   `size_x:Positive(required), size_y:Positive(required), size_z:Positive(required), center:Center3, mode:Mode`。
2. **`feature.cylinder`** — CLI `cylinder`；version=1；`summary_en="Create a cylinder"`；`label_zh="圆柱体"`（圆柱中心在 center，轴向 +Z，跨 z∈[−h/2,+h/2]）
   `radius:Positive(required), height:Positive(required), center:Center3, mode:Mode`。
3. **`feature.extrude`** — CLI `extrude`；version=1；`summary_en="Extrude a parametric profile"`；`label_zh="拉伸"`
   `profile:Profile(required), distance:number(required，可负，负=沿 −Z), mode:Mode`。
4. **`feature.revolve`** — CLI `revolve`；version=1；`summary_en="Revolve a parametric profile"`；`label_zh="旋转"`
   `profile:Profile(required), axis: oneOf[{const "X"},{const "Y"},{type:array,3 numbers, geom 层断言 ‖v‖−1 ≤ 1e-9，超差 ValidationError（消息带实际 norm 值）；不自动归一、不发 warning；(1,1,0)/(0,0,0) 为失败用例}]（required，绕该轴过原点）, angle_deg:number(0<..≤360, default 360.0), mode:Mode`。
5. **`feature.hole`** — CLI `hole`；version=1；`summary_en="Drill a predicate-located hole"`；`label_zh="孔"`
   **params_schema=根级 `{"$ref": "#/$defs/Hole"}`（#round11-3：根级 $ref 合法，键序取 Hole def properties 声明顺序 target_face/position/diameter/depth）**——字段语义：`target_face:FaceSelector(required), position:Position(required), diameter:Positive(required), depth:Depth(required)`；**target_face 必须解析为平面**（选到非平面固定 TopologyReferenceError reason="target-not-plane"）；孔轴=定位面外法向，blind 沿外法向反向（材料内部）延伸 value，through_all 沿轴穿透整个实体。
6. **`feature.hole_pattern`** — CLI `hole-pattern`；version=1；`summary_en="Pattern a predicate-located hole"`；`label_zh="孔阵列"`
   `base_hole: {"$ref": "#/$defs/Hole"}(required)（#round11-3：经 $ref 复用 Hole 共享定义，禁止内联复制）, pattern:Pattern(required)`；`pattern.kind="linear"` → ValidationError。
7. **`modify.fillet`** — CLI `fillet`；version=1；`summary_en="Fillet selected edges"`；`label_zh="圆角"`
   `edges: {type:array, items:EdgeSelector, minItems:1}(required), radius:Positive(required)`。
8. **`modify.boolean_cut`** — CLI 别名 `cut`（`cut` 唯一映射此 id）；version=1；`summary_en="Subtract an inline tool solid"`；`label_zh="差集"`
   `tool:Tool(required)`；**不接受 mode 键**（多余键 ValidationError）；法兰五孔不走此命令。

### A.2 约定

- 全部命令 version=1；id 集合恰好为这 8 个（注册表断言列表相等）。
- 所有参数对象 `additionalProperties:false`（未声明键一律 ValidationError，消息含点路径）。
- CLI 减法语义：feature 命令的减法经 `mode=cut` 键值（如 `cylinder radius=2 height=20 mode=cut`）；动词 `cut` 仅映射 modify.boolean_cut，二者永不混用。
- 全部 CommandSpec 固定 `undo_compensation="history_replay"`（唯一合法值，遵从技术路线 §7 的协议增强，非基线偏离）；T3 对任何其他值 ValidationError。
- **canonical to_cli 输出含 default 填充键（#round11-5）**：cylinder 行显式带 `center=[0,0,0] mode=new`、hole-pattern 行显式带 `pattern.start_angle_deg=0` 均为本规则的必然形态而非冗余；任何"省略默认值"的文本形态都不是 canonical 输出，examples 与 T11 快照以此为准。
- 本附录同时是阶段 2 工具 schema（OpenAI function-calling 形状）的参数部分来源；阶段 0 不写生成代码。

## 附录 B：计划文件 schema 与 affected_object 映射（`run --json` 权威规范）

### B.1 计划文件 flange_plan.json 权威 schema（additionalProperties:false 全层生效）

```json
{
  "plan_id": "string，可选；缺省时 CLI 以 `uuid.uuid4().hex` 生成（32 位小写十六进制；与 core Plan 构造契约同一规则，全项目唯一格式，禁止 `plan-<时间戳>` 形式）；存在时必须匹配正则 ^[0-9a-f]{32}$",
  "metadata": {
    "part_no": "string，必填",
    "revision": "string，必填",
    "material": "string，必填",
    "source": "string，必填",
    "part_name": "string，可选",
    "notes": "string，可选"
  },
  "steps": [
    {"id": "feature.cylinder", "version": 1, "params": {"radius": 40, "height": 8, "center": [0, 0, 0], "mode": "new"}, "affected_object": "cylinder_body"}
  ],
  "outputs": {
    "step": "string，可选；输出 STEP 路径（相对路径相对计划文件所在目录）",
    "stl":  "string，可选；输出 STL 路径",
    "archive": "string，可选；输出 .mc.json 路径"
  }
}
```

- 顶层键恰好 `plan_id?`、`metadata`（必填）、`steps`（必填、minItems 1）、`outputs?`；任何其他顶层键→ValidationError（退出码 1，坏计划=运行错误，不是用法错误）。
- metadata 键恰好六键（四必填+两可选），未知 metadata 键→ValidationError；steps 元素键恰好 `id/version/params/affected_object`，四键全必填；`affected_object` 必须等于 B.2 映射中该 id 的固定值，否则 ValidationError。
- params 必须通过该 id 的命令 schema（附录 A）校验后才允许进入 Plan。

### B.2 affected_object 固定值映射（恰好 8 值，全部唯一，单一来源）

| 命令 id | affected_object（固定字面量，8 值全部唯一） |
|---|---|
| feature.box | `box_body` |
| feature.cylinder | `cylinder_body` |
| feature.extrude | `extruded_body` |
| feature.revolve | `revolved_body` |
| feature.hole | `hole` |
| feature.hole_pattern | `hole_pattern` |
| modify.fillet | `edge` |
| modify.boolean_cut | `tool_body` |

- 映射表在 `src/mycad/core/document.py` 定义为模块级常量 `AFFECTED_OBJECTS: Mapping[str, str]`（单一来源；PlannedCommand 构造时查表，查不到 id→UnknownCommandError）；`builtin_commands` 与 T10 计划加载器均 import 此常量，禁止任何第二张表/硬编码。
- T7 静态断言测试：`AFFECTED_OBJECTS` 恰好 8 键且与注册表 id 集合相等；`len(set(values)) == 8`（8 值两两不同，反向查表无歧义）；值集合恰好等于 `{"box_body","cylinder_body","extruded_body","revolved_body","hole","hole_pattern","edge","tool_body"}`。

### B.3 `run --json` 执行语义（唯一权威顺序）

1. 读取并解析计划文件（文件不存在→退出码 2；JSON 语法损坏/不符合 B.1/命令 schema/affected_object 映射→退出码 1）；
2. 隐式 `new`：在**全新空 Document**上执行（不读取当前 REPL 文档；run 子命令永远自带独立文档，结束即释放）；
3. Plan 生命周期：draft → `confirm(actor="cli-local")` → 全部 steps 包进**一次** `execute_batch`（全部成功或 BatchRollbackError 整体回滚到空文档，退出码 1，stderr 含 failed_ordinal/failed_command_id）；
4. 执行成功后把 metadata 写入 Document：**六白名单键全部按"存在即写入"处理**——四必填键 part_no/revision/material/source 必写（值须为 str，允许空串）；两可选键 part_name/notes **仅当计划中存在时写入**（值为 str，空串也允许），缺省时 Document 不生成这两个键（绝不补空串、绝不静默丢弃已接受字段）；写完 metadata 与 execute_batch 无关，不进命令历史；
5. 按 `outputs` 导出：给出哪个键就导出哪个；**缺省规则**：三个键全缺省时，默认在计划文件同目录、以计划文件 stem 为基名导出全部三件（`<stem>.step`、`<stem>.stl`、`<stem>.mc.json`）；部分给出时未给出的不产出；目录不存在不自动创建（UnknownFormatError 不适用；路径写失败按运行错误=1）；
6. 保存的 .mc.json 是存档格式（附录/ADR-002 的六字段命令历史+metadata），**不是**计划文件的复制；stdout 打印三行产出路径；退出码 0。
- T10 测试：缺 metadata/未知顶层键/未知 metadata 键/affected_object 不匹配/空 steps 各→1；计划文件不存在→2；outputs 全缺省断言三件默认产物名；outputs 只声明 step 断言只有一件产物；batch 中途失败断言无任何产物且文档回滚空；中文路径产出；**plan_id 规则两例**：缺省运行两次生成的 id 均匹配 `^[0-9a-f]{32}$` 且互不相等；显式非法值 `"plan-2026-09-17"`（非 32 hex）→1（ValidationError）；**metadata 可选键两例（#round7-7）**：计划含 part_name/notes 时导出的 .mc.json 中两键保留且值逐字相等；计划不含两键时 .mc.json 的 metadata 对象中不存在这两个键（不是空串）；另测空串值往返保留。
- **内嵌示例必须字面合法（happy 用例）**：测试从 B.1 代码块中解析出 steps[0]（feature.cylinder/radius40/height8/center[0,0,0]/mode=new/affected_object=cylinder_body），断言它同时通过 B.1 计划校验器、附录 A 命令 schema 校验器与 B.2 映射校验；该 JSON 代码块内 steps[0] 是真实值而非说明文字，schema 形状说明仅存在于同块的其他字段字符串中，执行者不得把示意说明当合法计划。
- T11 的 `examples/flange_plan.json` 必须是 B.1 的手写实例（metadata 四必填填 FLANGE-DEMO-001/A/Q235/example，steps 与 flange_script.txt 等价，outputs 全缺省以走默认命名）；验收测试同时断言该文件被 B.1 校验器接受、affected_object 逐元素等于 B.2。
