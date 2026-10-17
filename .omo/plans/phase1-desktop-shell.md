# phase1-desktop-shell - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**Who this is for and what changes for them:** 给 CAD 最终用户：此前只能用命令行/脚本驱动建模，本阶段交付完整桌面窗口——点菜单、点命令库、看三维预览、在确认卡片上按「执行」即可完成法兰件从建模到导出的全流程，无需记任何命令。

**What you'll get:** 一个五区布局的桌面应用（菜单/工具栏/左侧命令库/中间三维视口/右侧结构属性面板/底部确认栏/状态栏），文件的新建-打开-保存-导出，撤销重做，以及三平台（两种 Linux + Windows）自动化测试全绿；外加国产平台（arm 架构与龙芯）的实测结论。

**Why this approach:** 三维内核的当前选型不允许两套界面库同进程共存，故视口先用轻量网格预览把壳做完整、接口留好，后期一键换正式渲染；确认管道直接复用阶段 0 已验证的六态计划状态机，命令必经确认才执行。

**What it will NOT do:** 不含任何 AI/网络功能（留阶段 2）；不新增建模命令；不做多文档窗口与后台线程；不做安装包。

**Effort:** XL
<!-- Effort is exactly ONE band, never hours/days. Quick = single edit, minutes of agent work; Short = one focused change, a few files; Medium = multi-file feature in one session; Large = several waves, one long session; XL = multi-session or architectural work. A written duration is rewritten to a band. -->
**Risk:** Medium - 无头 CI 中 OpenGL 视口的三平台差异，以及守卫/许可迁移须一次到位
**Decisions to sanity-check:** 网格视口占位 + pyqtgraph.opengl 渲染库；PySide6 进主依赖（非可选）；「聊天」= 计划卡片确认而非自然语言；单文档窗口；同步重建无线程。

Your next move: run a high-accuracy review or start execution ($ulw-execute). Full execution detail follows below.

---

> TL;DR (machine): XL | Medium | PySide6 五区桌面壳 + 网格视口 + 六态确认管道 + 守卫/NOTICE 迁移 + T2/T3 平台收口；16 todos in 4 waves + F1-F4 final wave.

## Scope
### Affected user and ideal state
<!-- From the draft ledger: who this touches and how they use the result, then one IS row per property with its reason, then one GAP row per difference with its reason. Every todo below closes a GAP row; ## Success criteria proves every IS row. -->
**Affected user:** U1 CAD 最终用户（工程师/爱好者，首期=项目验收牵引者本人）今天只有 CLI/REPL/JSON 脚本入口，之后获得完整 GUI 法兰工作流；U2 插件作者的命令自动出现在左栏命令库；U3 阶段 2 的 Agent/MCP 客户端获得 confirmation_token 的产品侧交互落点（本计划的确认按钮）；U4 维护者获得 T1 三平台含 GUI 的 CI、分层守卫与 NOTICE 持续可信。

| Row | Statement | Reason |
| --- | --- | --- |
| IS-1 | 主窗五区齐全（菜单/Toolbar/左栏/视口/右栏/底栏/状态栏）；Toolbar 可消隐、四边停靠、可锁定、QSettings 记忆恢复 | F-UI-01/02/06 全 P0；UI 初稿 §2-§4 |
| GAP-1 | 无 ui 包、无 gui 入口，全部缺失 | 阶段 0 交付边界是 headless |
| IS-2 | 左栏搜索+可折叠分类命令库，内容注册表驱动（八条 P0 + 插件贡献自动出现） | F-UI-03 P0；NF-06 注册式扩展 |
| GAP-2 | 命令只存在于 CLI | 同上 |
| IS-3 | 右栏 结构/属性/选项 三 Tab 常驻可用；显示/测量占位 Tab 在位；结构树根=文档节点、按 基准/草图/特征/实体 分组、点击↔视口联动；无选中时属性页显示文档级属性 | F-UI-04、F-TREE-01、F-PROP-01、F-OPT-01 全 P0 |
| GAP-3 | 无任何面板 | 同上 |
| IS-4 | 视口：旋转/平移/缩放/适应窗口；着色/线框切换；点选特征与结构树双向高亮 | F-MOD-02/03 P0、F-MOD-04 P1（一并做，成本低） |
| GAP-4 | 无视口；cadquery-ocp-novtk 选型（pyproject.toml:12-14 注释）使 OCCT AIS 同进程嵌入不可行（双 Qt 冲突）→ 走路线 §1「早期网格预览过渡」+ §8 缓解 | 技术路线既定缓解路径 |
| IS-5 | 底栏 Chat\|CLI：Chat 渲染计划卡片（命令名/参数/影响对象），执行/编辑/取消三键；编辑与右栏「选项」Tab 双向同步；确认后才提交 Command Bus；失败整批回滚且 UI 可见 | F-UI-05、F-AGT-02/03/04 全 P0 |
| GAP-5 | 确认管道只存在于 headless CLI（run --json 的确认流） | 阶段 0 边界 |
| IS-6 | 文档生命周期全 GUI：新建/打开/保存/另存/导出 STEP+STL；未保存变更关闭有提示 | F-DOC-01/02 P0 |
| GAP-6 | 文件操作只在 CLI | 同上 |
| IS-7 | CLI/GUI 同源：GUI 确认执行的计划在 CLI 有等价命令文案；`mycad gui` 启动入口 | F-AGT-05（P1，复用 grammar 成本低）；多入口同源原则 |
| GAP-7 | 无 gui 子命令 | 同上 |
| IS-8 | 跨平台收口：T1 三平台 CI 含 GUI offscreen 测试全绿；T2 aarch64 QEMU 回归补齐；T3 龙芯 spike 产出 go/no-go 决议并更新 ADR-006 | ADR-006 第 2/5 条是阶段 1 承诺 |
| GAP-8 | T2 只有 wheel 可得性证据无端到端验证；T3 无 spike | ADR-006:31-32 |
| IS-9 | 合规与守卫迁移：NOTICE 归属新增闭包成员（PySide6/shiboken6/pyqtgraph/PyOpenGL；numpy 已在册）；M1 禁词表改造（PySide6 仅 ui/ 可引）；test_layering 扩展；core 依旧 Qt-free；零 type:ignore（todo 9 的 typings/ stub 是唯一预设豁免机制） | NF-05；技术路线 §9 |
| GAP-9 | PySide6 目前是 M1 禁词（tests/test_scope_audit.py:29,75）；NOTICE 无 Qt 条目 | 阶段 0 反 GUI 纪律需定向解除 |
| IS-10 | headless 零回归：CLI/REPL/脚本行为不变，既有 802 测试基线保持绿 | 桌面壳不得侵蚀内核契约 |
| GAP-10 | 引入 GUI 主依赖带来安装面/闭包变化风险 → 由全量基线 + 三平台 CI 守护 | 风险型 GAP |

### Must have
- C1 ui-shell：QMainWindow 五区布局 + 菜单七项 + Toolbar(QSettings) + 状态栏 + `mycad gui` 入口 + 文档生命周期（单文档窗）。
- C2 ui-panels：左栏注册表驱动命令库（搜索+分类折叠）+ 右栏五 Tab（结构/属性/选项常驻，显示/测量占位）。
- C3 viewport：core ViewportData 协议（依赖倒置，mesh 复用 core Tessellation）+ geom 每命令一状态快照网格化 + ui 网格渲染（仅最终快照上屏；旋转/平移/缩放/fit、着色/线框、点选↔树双向高亮）；渲染库 = pyqtgraph.opengl（用户已选）。
- C4 plan-confirm：底栏 Chat|CLI Tab + 计划卡片 + 选项 Tab 参数编辑双向同步 + core.plan 六态确认管道 + 批事务回滚反馈。
- C5 guards-compliance：layering/M1 守卫迁移 + NOTICE 闭包归属 + CI offscreen + README 快速开始。
- C6 platform-t2t3：aarch64 QEMU 回归（T2 补齐）+ 龙芯 spike → go/no-go 决议（T3，更新 ADR-006）。
- UI 初稿 §11 验收五条全部落地（含 tests/test_acceptance_flange.py::test_ui_layout_acceptance 解跳）。
- 需求 §8 验收基线第 1/3/4/5 条的 GUI 面向收口；第 2 条的 Chat 自然语言部分按 ADR-004 留阶段 2，计划卡片确认部分本阶段完成。

### Must NOT have (guardrails, anti-slop, scope boundaries)
- 无任何 LLM/MCP/网络代码；无自然语言→计划解析（ADR-004：阶段 2）。
- 不新增几何命令（P1/P2 id 不实现、不注册；保留 id 命名空间规则照旧）。
- 不做多文档/MDI/多窗；不做工作线程/异步重建。
- 不做装配、工程图、草图约束（需求 §3.2 Out + 阶段 3）。
- 不改 .mc.json v1 schema、不动 build123d/OCP 版本 pin（-novtk 保持；pyproject:12-14 注释按阶段 1 现实改写但不改 pin 本身）。
- core/ 不引 PySide6/Qt/numpy（signals.py 抽象即为此设计）；ui/ 不引 build123d/OCP/mycad.geom（AST 规则禁到包名，堵 from mycad.geom.kernel 传递后端；视口数据走 ViewportData 协议）；ui/ 允许 numpy（pyqtgraph 生态，分层规则只约束 core）。
- 不做 AppImage/Flatpak 打包（路线 §4：开发期不以打包为阻塞）。
- 不做 Node-RED 流程画布、Kivy、Electron（需求 §3.2 + 路线 §10）。
- 不为单文件加 ruff per-file ignore；零 type:ignore 纪律保持。
- 不动 CI matrix 的 T1 三 job 边界（ADR-006:31-32：T2/T3 验证在 CI 外产出证据）。

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: **随每个 todo 写测试**（用户已选）——UI 用 pytest + pytest-qt（QT_QPA_PLATFORM=offscreen），core/geom 用纯 pytest；TDD 或 tests-after 由执行者按 todo 自然性选择，但每个 todo 必须带可执行测试。
- 每 todo scoped 四门：`uv run ruff check <path>` / `uv run ruff format --check <path>` / `uv run basedpyright <path>` / `uv run pytest <scoped path> -q`；全量四门只在最终集成（todo 13）与 final wave 跑。
- 红绿探针纪律沿用（阶段 0 AGENTS.md）：守卫类 todo 必须做「注入违规→红→还原→绿」闭环。
- Evidence: `.omo/evidence/task-<N>-phase1-desktop-shell.md`（每 todo 一份：命令、输出摘要、探针记录）。
- CI：每语义提交后三平台必须全绿才算该 todo 关闭；junitxml 失败经 scripts/report_junit_failures.py 自报告为 Actions 注解（阶段 0 已上线）。

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

- **Wave 1（地基）**：todo 1（依赖+守卫+NOTICE）先行落地后，todo 2/3/4 并行（core 协议、geom 网格化、ui 骨架）。todo 2/3 不依赖 PySide6，可与 todo 1 内部交替。
- **Wave 2（壳与面板）**：todo 5/6/7/8 全并行（均只依赖 todo 4 的骨架与既有 core API）。
- **Wave 3（视口与确认管道）**：todo 9/11 先行；todo 10 依赖 7+9；todo 12 依赖 6+7；todo 13 收口（依赖 5-12 全部）。
- **Wave 4（平台与文档）**：todo 14/15/16 并行（15/16 实际上只依赖 todo 1，可提前启动；14 需 13 完成后写实测内容）。

> 显式延后（.omo/plans/phase1-backlog.md 已登记，F1 合规审计勿 flag）：ruff PT/PL 规则集、M3/M7 守卫机器化、图标集（初稿 §4.2）与 QSS 主题（§9）、底栏高度/折叠一行入口（§7.3）。

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | — | 4,9,13,15,16 | 2,3 |
| 2 | — | 3(实现方参考),9,13 | 1,3 |
| 3 | 2（协议定义） | 9,13 | 1,2 |
| 4 | 1（PySide6 可用） | 5,6,7,8,11,13 | 2,3 |
| 5 | 4 | 13 | 6,7,8 |
| 6 | 4 | 12,13 | 5,7,8 |
| 7 | 4 | 10,12,13 | 5,6,8 |
| 8 | 4 | 13 | 5,6,7 |
| 9 | 2,3,4 | 10,13 | 11,12 |
| 10 | 7,9 | 13 | 11,12 |
| 11 | 4 | 13 | 9,10,12 |
| 12 | 6,7 | 13 | 9,10,11 |
| 13 | 5,6,7,8,9,10,11,12 | 14 | —（波内收口） |
| 14 | 13 | — | 15,16 |
| 15 | 1 | — | 14,16（可提前至 W1 后启动） |
| 16 | 1 | — | 14,15（可提前至 W1 后启动） |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [ ] 1. 依赖引入与守卫/合规迁移（PySide6 进主依赖 + M1/layering/NOTICE 一次到位）
  What to do / Must NOT do: pyproject.toml [project.dependencies] 增 PySide6 与 pyqtgraph（版本由 uv 解析并锁入 uv.lock；**不动 build123d/cadquery-ocp-novtk pin**）；dev 组增 pytest-qt；改写 pyproject:12-14「T1 forbids VTK/PySide6/CadQuery」注释为阶段 1 现实（PySide6 解禁仅限 src/mycad/ui/，VTK 经 OCP 仍禁，CadQuery 仍禁）。守卫迁移（动手前先通读 tests/test_scope_audit.py 与 tests/test_layering.py 全文）：①import 扫描是 AST 级、仅扫 src/**/*.py（pyproject/NOTICE/docs/.github/tests 本不在扫描面，无需豁免）——a) FORBIDDEN_DISTRIBUTIONS（:73-92；test_runtime_closure_clean :422-438 是闭包级断言）移除 pyside6+shiboken6 两项（保留 pyside2/pyqt5/pyqt6/vtk；闭包禁词不可路径限定，删词是唯一合法解除法）；b) FORBIDDEN_IMPORT_ROOTS（:26-58）为 PySide6/shiboken6 加 ui 豁免前缀 src/mycad/ui/（镜像 BACKEND_ALLOWED_PREFIX :63 机制；pyqtgraph 今不在任何禁词表无需动作；PySide2/PyQt5/PyQt6/qtpy/vtk 保持全域禁），顺手补 tkinter/wx 进禁词表（backlog M1 项收口）；②tests/test_layering.py 常量重构（:19/:21-28/:34）：build123d/OCP 仅 geom/ 与 app.py 可引；numpy 放行 geom/ 与 src/mycad/ui/（pyqtgraph 生态）；TESTS_ALLOWED_IMPORT_PREFIXES 增 tests/ui/；新 AST 规则「src/mycad/ui/** 禁 import mycad.geom」——禁到包名才堵得住 from mycad.geom.kernel import 的传递后端；core 的 Qt-free 由 tests/core/test_signals.py:95-105（signals 子进程检查，不动即绿）继续承担（test_layering 里并无「core Qt-free」既有断言，勿凭空造）；app.py 仍是唯一 core+geom 桥（ui 可 import mycad.app）；③NOTICE 增恰四个新条目：PySide6/shiboken6（LGPL）、pyqtgraph（MIT）、PyOpenGL（BSD-3）——numpy 已在闭包与 NOTICE（经 build123d，NOTICE:83；MAJOR_COMPONENTS 见 test_notice.py:25-31），勿重复添加；同时 grep uv.lock 新依赖子树的 sys_platform 平台条件项（colorama 教训）写入平台差异注记（backlog 该项收口）；④tests/test_notice.py 与 test_scope_audit.py 的闭包基线（46→新计数，以真实 uv tree 输出为准）同步；⑤若 ubuntu CI runner 缺 GL 离屏库，ci.yml ubuntu job 加 apt 安装（libgl1、libegl1、libxkbcommon-x11-0、libglib2.0-0），同时保持 tests/test_ci_workflow.py REQUIRED_TOKENS 断言同步；apt 后 GL 仍不可用的兜底阶梯在 todo 9 钉死（本 todo 只管 apt 半）。Must NOT：不改 .mc.json schema、不引 PyQt5/VTK、core 零 Qt、不加 per-file ignore、零 type:ignore。
  Closes: GAP-9（守卫半）；为全部后续 todo 解锁
  Parallelization: Wave 1 | Blocked by: — | Blocks: 4,9,13,15,16
  References (executor has NO interview context - be exhaustive): pyproject.toml:12-18（deps+注释）、:23-34（dev 组）、:46-55（addopts）、:87-95（既有 carve-out）；tests/test_scope_audit.py:26-58（FORBIDDEN_IMPORT_ROOTS）、:63（BACKEND_ALLOWED_PREFIX 样板）、:73-92（FORBIDDEN_DISTRIBUTIONS）、:391（FORBIDDEN_CI_TOKENS）、:423,:454（subprocess encoding 固化——新增 subprocess 调用照此）；tests/test_layering.py（分层不变量全文——重点 :19/:21-28/:34 常量区）；tests/core/test_signals.py:95-105（core Qt-free 实际承担者，不动）；tests/test_notice.py:62,:73（闭包断言）；NOTICE（46 分发现状含 colorama 平台差异段）；.github/workflows/ci.yml；tests/test_ci_workflow.py:24（"pytest -q" 字面量断言与 REQUIRED_TOKENS 列表）；AGENTS.md「T1 分层硬规则」与「零类型抑制」节
  Acceptance criteria (agent-executable): `uv sync` 成功且 uv.lock 更新；`uv run pytest tests/test_layering.py tests/test_scope_audit.py tests/test_notice.py tests/test_ci_workflow.py -q` 全绿；`grep -rn "PySide6" src/mycad/core/` 零命中；NOTICE 含上述五个新条目且 `uv run pytest tests/test_notice.py -q` 绿；红绿探针：临时在 src/mycad/core/ 加 `import PySide6` → test_layering 红 → 还原 → 绿（证据入 task-1）。
  QA scenarios (name the exact tool + invocation): happy = 上述 scoped pytest 全绿；failure = 注入探针红。Evidence `.omo/evidence/task-1-phase1-desktop-shell.md`
  Commit: Y | build(deps): add PySide6+pyqtgraph and migrate layering/M1/NOTICE guards for the ui package
  Recommended task executor category: unspecified-high

- [ ] 2. core ViewportData 依赖倒置协议
  What to do / Must NOT do: src/mycad/core/ 新增 viewport_protocol.py（风格对齐 ports.py）：`ViewportData` frozen dataclass = feature_id: str + mesh: Tessellation（**复用 mycad.core.geometry_types.Tessellation 的 vertices/triangle_indices 及 __post_init__ 索引校验——不新写顶点/索引字段，守单一定义点规则**）+ 可选 normals: tuple[tuple[float, float, float], ...]（ViewportData 层）+ `ViewportPort` Protocol（`viewport_data() -> tuple[ViewportData, ...]`，每 feature_history ordinal 一条=该命令执行后的整体状态快照；feature_id=命令 id+ordinal——快照语义细节在 todo 3）。线框边由渲染侧从三角形边去重派生（协议不带边数据，减协议面）。tests/core/test_viewport_protocol.py：契约测试（空元组语义、索引校验红路、frozen 不可变）。Must NOT：不 import Qt/numpy/build123d；不重复定义顶点/索引字段（Tessellation 已有）；不改既有 Kernel Protocol 的 reset/apply 两方法；不带渲染语义（颜色/光照）进 core。
  Closes: GAP-4（core 半）
  Parallelization: Wave 1 | Blocked by: — | Blocks: 3,9,13
  References: src/mycad/core/geometry_types.py:59-77（Tessellation——直接复用；core/__init__.py:21,59 已导出）；src/mycad/core/kernel_protocol.py:16-26（既有两方法协议——本协议是第三个依赖倒置）；src/mycad/core/ports.py:21-42（ExportableKernel 模式样板）；src/mycad/core/document.py（feature_history 序）；AGENTS.md「改模型只能经 Bus」
  Acceptance criteria: `uv run pytest tests/core/test_viewport_protocol.py -q` 绿；`uv run basedpyright src/mycad/core` 0 errors；`uv run pytest tests/test_layering.py -q` 绿（core 无新依赖）。
  QA scenarios: happy = 协议契约单测；failure = 越界索引构造抛 ValueError 的测试。Evidence `.omo/evidence/task-2-phase1-desktop-shell.md`
  Commit: Y | feat(core): add ViewportData protocol for decoupled mesh preview
  Recommended task executor category: deep-low

- [ ] 3. geom 按特征网格化实现 ViewportPort
  What to do / Must NOT do: src/mycad/geom/kernel.py 的 BuildKernel 实现 ViewportPort，**快照语义**：apply() 成功后对执行后的 Part deepcopy 追加进 list[tuple[str, Part]]（feature_id=命令 id+ordinal；undo/redo 走全量重放=重跑 apply，列表自然重建）；viewport_data() 对每快照调 geom/query.py 的 build_tessellation（deepcopy(part).tessellate(...) 语义，:80-84 陈旧三角化注记照抄——**勿用 BRepMesh_IncrementalMesh：src 零用例，STL 导出走 build123d.export_stl**）装 ViewportData.mesh=Tessellation（tuple 化，不引 numpy 类型进协议）；空文档返回空元组。tests/geom/ 新增：给定法兰命令序列（cylinder+hole_pattern 即 F3 用过的序列），viewport_data() 条数=特征数、每条顶点数>0、同容差两次调用结果一致、更细容差三角形数单调不减（kernel.py:114-117 已承诺的契约）；失败路=空文档。Must NOT：不做缓存/失效逻辑（阶段 1 同步重建，geometry_rebuilt 后整体重取）；上屏渲染只画最终快照（渲染语义归 todo 9）；ui 无关；不在 geom 之外引 OCP。
  Closes: GAP-4（geom 半）
  Parallelization: Wave 1 | Blocked by: 2 | Blocks: 9,13
  References: src/mycad/geom/kernel.py（BuildKernel 单例；:84 self._part、:101-104 apply 替换语义、:111-119 tessellate 契约）；src/mycad/geom/query.py:71-96（build_tessellation——deepcopy+tessellate 既有用法）；src/mycad/core/geometry_types.py:59-77（Tessellation）；tests/geom/（既有测试风格）；todo 2 产物 viewport_protocol.py
  Acceptance criteria: `uv run pytest tests/geom -q` 绿；`uv run basedpyright src/mycad/geom` 0 errors；test_layering 绿。
  QA scenarios: happy = 法兰序列网格化断言；failure = 空文档空元组。Evidence `.omo/evidence/task-3-phase1-desktop-shell.md`
  Commit: Y | feat(geom): per-feature mesh extraction implementing ViewportPort
  Recommended task executor category: deep-low

- [ ] 4. ui 包骨架 + `mycad gui` 入口 + offscreen 冒烟
  What to do / Must NOT do: 新建 src/mycad/ui/（__init__.py、main_window.py，SPDX 头）：QMainWindow 五区容器——左 QDockWidget（objectName=leftPanelDock）、中央占位 QWidget（objectName=viewportHost，todo 9 换真视口）、右 QDockWidget（rightPanelDock）、底 QDockWidget（bottomPanelDock）、QToolBar（mainToolBar）、QStatusBar；各Dock 允许浮动/关闭按初稿 §2。CLI：src/mycad/cli/__main__.py 增 `gui` 子命令 → build_app() + new_document() + 主窗 show（信号循环）；HELP_TEXT 同步增 gui 行（tests/cli/test_repl.py:93-96 帮助断言随本 todo 更新）；tests/ui/conftest.py（pytest-qt qapp fixture + os.environ.setdefault("QT_QPA_PLATFORM","offscreen")——**仅此机制**：pytest ini 不能设 env（需 pytest-env 新依赖，拒）；setdefault 保留逐测试覆写能力，todo 9 的 Windows native 兜底依赖它）。tests/ui/test_shell_smoke.py：窗体构建、五区 objectName 全存在、**GL 能力探针（QOffscreenSurface+QOpenGLContext.create() 成功断言——Wave 1 即让三平台 CI 暴露 GL 现实，不等到 todo 9）**、QTimer 单触发后干净退出。Must NOT：不做面板内容（todo 5-8）、不引 pyqtgraph（todo 9）、不动 core/geom、gui 子命令不做任何 headless 无法测试的路径（无 daemon/无 fork）。
  Closes: GAP-1（骨架半）、GAP-7（入口半）
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 5,6,7,8,11,13
  References: docs/UI设计初稿.md §2（五区布局与区域职责）、§10（PySide6 部件建议：QMainWindow/QDockWidget|QSplitter/QToolBar）；src/mycad/app.py:36-49（AppServices）、:101-117（new_document：kernel.reset 独占、handler map 装配）；src/mycad/cli/__main__.py（子命令注册模式）；src/mycad/cli/session.py（REPL 入口模式参考）；pyproject.toml:46-55（pytest addopts）
  Acceptance criteria: `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui -q` 绿；`uv run mycad --help` 显示 gui；scoped 四门绿；CI 三平台绿（本 todo 起每提交都须三平台绿）。
  QA scenarios: happy = 冒烟窗体测试；failure = 五区缺一 objectName 断言红（探针）。Evidence `.omo/evidence/task-4-phase1-desktop-shell.md`
  Commit: Y | feat(ui): five-zone main window shell and `mycad gui` entry point
  Recommended task executor category: unspecified-high

- [ ] 5. 菜单七项 + Toolbar 行为 + QSettings + 状态栏
  What to do / Must NOT do: 菜单按初稿 §3 七项**逐字**：文件/编辑/视图/特征/工具/智能体/帮助。文件=todo 8 占位（本 todo 先挂 enabled=False 或空 slot 注明；截图/导入（F-DOC-03）占位 disabled）；编辑=撤销/重做（bus.undo/redo 既有）+删除/选择过滤器（enabled=False 占位）；视图=着色/线框切换动作占位（todo 9 挂真 slot）+ Toolbar/各 Dock/底栏显隐开关；特征=「打开左栏命令库」（与左栏重复可接受）；工具=选项（QSettings 说明）/单位（只读 mm）/测量（占位 disabled）/重建（触发视口重取，接 todo 9）；智能体=查看待确认计划（切底栏 Chat Tab 并聚焦活动卡片——todo 12 产物）+清空对话（清卡片流）；帮助=快捷键列表/关于/开源许可说明（Apache-2.0 + 指向 NOTICE——PySide6 LGPL 的产品内归属面）。Toolbar：可消隐（视图+右键菜单）、四边可停靠、可锁定（QToolBar.setMovable/setFloatable + lock 动作）、QSettings 记忆（saveState/restoreState + geometry，org="MyCAD"/app="MyCAD" 常量）。状态栏五字段（F-UI-06 P0 + 初稿 §8）：当前命令/空闲提示 + 选择计数 + 单位 mm + 重建状态（订 post_command/geometry_rebuilt 并集，与 todo 8/9 同一信号集）+ 修改标记。图标与 QSS 本期延后：文本按钮 + 默认样式（初稿 §4.2 图标 12-17、§9 工业灰蓝、§7.3 底栏折叠已登记 backlog）。tests/ui/test_menus_toolbar.py：七菜单（§3 名称逐字）存在、toggle→saveState→restoreState 往返一致、锁定态断言、状态栏五字段变更。Must NOT：不加初稿未列菜单项；关于不写版本号以外内容；不做快捷键全覆盖（只做初稿列出的）。
  Closes: GAP-1（交互半）
  Parallelization: Wave 2 | Blocked by: 4 | Blocks: 13
  References: docs/UI设计初稿.md §3（菜单七项）、§4（Toolbar 消隐/换边/锁定/QSettings/最小图标 12-17）、§8（状态栏）、§10；todo 4 产物 src/mycad/ui/main_window.py；src/mycad/core/bus.py（undo/redo）；src/mycad/cli/（commands/plugins 子命令输出逻辑复用面）
  Acceptance criteria: `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_menus_toolbar.py -q` 绿；scoped 四门绿。
  QA scenarios: happy = 菜单/工具栏/状态栏断言；failure = restoreState 后工具栏位置丢失探针红。Evidence `.omo/evidence/task-5-phase1-desktop-shell.md`
  Commit: Y | feat(ui): menus, dockable lockable toolbar with QSettings persistence, status bar
  Recommended task executor category: visual-engineering

- [ ] 6. 左栏注册表驱动命令库
  What to do / Must NOT do: 左栏：搜索 QLineEdit + QTreeWidget 分类折叠树；数据=CommandRegistry 全量 spec（按命令 id 首段分组——CommandSpec 无 category 字段，registry.list_by_category（registry.py:105-113）即此语义；八条 P0 分 feature/modify 两类）；双击条目 → 构造 **PlanDraftController**（本 todo 新建 src/mycad/ui/plan_draft.py：持有 core.plan.Plan + selected_step_index；API steps()/params_of(step)->dict/set_params(step,dict)（经 registry validate_params 校验）/select_step(i)；Qt 信号 params_changed(step, params)/plan_replaced()——todo 7/12 共享的草稿契约一次钉死）；底部说明「插件命令自动出现」；register_left_item 扩展约定写 API 注释（初稿 §5.3）。tests/ui/test_command_palette.py：八条 P0 全出现且分组正确；PlanDraftController 契约（set_params 经校验、params_changed 发射）；搜索「hole」过滤剩 2 条（feature.hole/hole_pattern）；搜索同时匹配 id 与 label_zh（registry.search 默认排除中文、docstring 注明留给 Phase 1 UI——UI 侧过滤或扩展 search(include_zh=True)；「孔」可搜出两条 hole）；插件同源——用既有 discoverer 注入缝（build_app(discoverers=…) app.py:52-64 + tests/fixtures/plugins 夹具；**不做 editable 安装**）后其贡献命令出现在树里。Must NOT：不新增命令 id；不做拖拽（初稿 P0 只要求点击）；不实现灰显 P1/P2（registry 无即自然满足）。
  Closes: GAP-2
  Parallelization: Wave 2 | Blocked by: 4 | Blocks: 12,13
  References: docs/UI设计初稿.md §5（含 5.3 命令清单表 P0/P1/P2 与 register_left_item）；src/mycad/commands/registry.py（CommandRegistry.list 接口）；src/mycad/builtin_commands/specs.py:27-167（八条 P0 的 id/category/params）；src/mycad/app.py（_handler_map 插件贡献装配）；plugins_examples/mycad_plugin_demo/；tests/fixtures/plugins/（插件测试夹具模式）；AGENTS.md「Plugin 命令贡献契约」
  Acceptance criteria: offscreen scoped pytest 绿（含 demo 插件用例）；scoped 四门绿。
  QA scenarios: happy = 八命令+插件命令出现；failure = 未装插件时 demo 命令不出现（负向断言）。Evidence `.omo/evidence/task-6-phase1-desktop-shell.md`
  Commit: Y | feat(ui): registry-driven categorized command library with search
  Recommended task executor category: visual-engineering

- [ ] 7. 右栏五 Tab（结构/属性/选项 + 显示/测量占位）
  What to do / Must NOT do: 右栏 QTabWidget 五页：「结构」QTreeWidget 树根=文档节点（part_name/文件名 stem——F-TREE-01），下按 基准/草图/特征/实体 四分组（阶段 1 数据源=Document.feature_history（特征组）+named_groups（实体/组）；基准/草图组空显示占位文案），节点=命令 id+用户可读名，点击发 selectionChanged（接 todo 10 双向联动）；「属性」=当前选中命令的 spec 参数只读表（参数名/类型/当前值）；无选中时显示文档级属性（document.metadata 六键只读表，document.py:147-150——F-PROP-01 P0 后半）；「选项」=当前草稿命令的参数编辑表（数据源=todo 6 的 PlanDraftController——本 todo 编辑组件对其 API 编码、测试用 fake，todo 12 接真实例；selected_step_index 即「选项 Tab 编辑哪一步」的唯一答案；落地 QTableWidget 参数编辑→dict 的受控组件与变更信号）；「显示」「测量」=占位页（disabled 说明文字，初稿 §6）。register_right_tab 约定 API 注释。tests/ui/test_right_tabs.py：五 Tab 在位；喂三命令文档后结构树特征组 3 节点+文档根节点在位；属性表显示 spec 参数、空选择显示文档级属性；选项页编辑→信号携带新 dict。Must NOT：不做测量；不做草图/基准真数据；属性表不做编辑（只读）。
  Closes: GAP-3
  Parallelization: Wave 2 | Blocked by: 4 | Blocks: 10,12,13
  References: docs/UI设计初稿.md §6（五 Tab+分组+自动跳转表+register_right_tab）；src/mycad/core/document.py（feature_history/named_groups 读取接口——只读不经 Bus）；src/mycad/builtin_commands/specs.py（params schema 结构）；src/mycad/core/signals.py:20-30（named_group_added/removed 驱动树刷新）
  Acceptance criteria: offscreen scoped pytest 绿；scoped 四门绿。
  QA scenarios: happy = 三命令文档树+属性+选项断言；failure = 空文档树仅空分组占位。Evidence `.omo/evidence/task-7-phase1-desktop-shell.md`
  Commit: Y | feat(ui): right dock with structure/properties/options tabs
  Recommended task executor category: visual-engineering

- [ ] 8. 文档生命周期（新建/打开/保存/另存/导出/未保存提示）
  What to do / Must NOT do: 文件菜单落地：「新建」=经 app.new_document()（kernel.reset 独占路径，绝不直调 kernel.reset）+ 重置 UI 面（树/视口/草稿）；「打开」=QFileDialog 选 .mc.json → persistence 加载（坏文件报 QMessageBox 不崩）；「保存/另存」=持久化 API；「导出」=STEP/STL 两动作走 formats registry 既有 provider（QFileDialog 定路径）；dirty 追踪：绑定 document.is_dirty——订阅 **post_command/geometry_rebuilt/command_amended/metadata_changed/named_group_added/named_group_removed 并集**信号集（两族互不可替代：单命令 bus.execute 与 execute_batch 每步只发 pre/post_command（bus.py:101/115；批成功路径无 _rebuild，bus.py:196-235 逐行读证），undo/redo/edit_and_replay/批回滚恢复只发 geometry_rebuilt（bus.py:136/149/181/224→165）——只订任一族都漏：CLI Tab 单命令与计划卡片批执行缺 post_command 则 dirty 永不置位（oracle 双审 B1），重放路径缺 geometry_rebuilt 则 undo 后不复位（Metis G10 既有发现），故必须并集）；保存成功后显式调 document.mark_clean()（persistence.save_document 不清脏标记，document.py:172-174）；关闭/新建时有脏变更 → QMessageBox「保存/放弃/取消」三选；单文档语义=替换当前（A4）。tests/ui/test_document_lifecycle.py（tmp_path 往返：new→命令→save→reopen 内容一致；undo 后关闭→拦截仍出现；保存后 is_dirty=False；脏态关闭拦截用 monkeypatch 拦 dialog 模拟三选）。Must NOT：不绕过 CommandBus 改 Document；不直调 kernel.reset；不做多文档；导出不新增格式。
  Closes: GAP-6
  Parallelization: Wave 2 | Blocked by: 4 | Blocks: 13
  References: src/mycad/app.py:101-117（new_document 唯一合法装配+reset 路径）；src/mycad/core/persistence.py（load/save/new_document API；:111-135 save 不清脏）；src/mycad/core/document.py:172-174（mark_clean——UI 保存成功后调用）；src/mycad/core/signals.py:20-30（九信号）；src/mycad/formats/registry.py（provider 选择）；ADR-001（唯一写入路径）、ADR-002（.mc.json v1）；tests/core/ 既有 persistence 测试（API 用法参考）
  Acceptance criteria: offscreen scoped pytest 绿（含往返一致与拦截）；scoped 四门绿。
  QA scenarios: happy = 往返一致；failure = 坏 JSON 打开→错误框且进程存活。Evidence `.omo/evidence/task-8-phase1-desktop-shell.md`
  Commit: Y | feat(ui): document lifecycle with unsaved-change guard
  Recommended task executor category: unspecified-high

- [ ] 9. 视口渲染（pyqtgraph.opengl）
  What to do / Must NOT do: src/mycad/ui/viewport.py：GLViewWidget 装 viewport_data()→**场景仅渲染最终快照**（一条整体 MeshData 着色 + LineSegment 边，三角形边去重得线框；中间快照条目供 todo 10 拾取/树联动，不上屏）；交互：鼠标旋转/平移/滚轮缩放（GLViewWidget 内置）+ `fit_view()`（算整体 bbox 设 camera distance/center）；着色/线框切换动作挂 todo 5 视图菜单；刷新订阅=致 todo 8 同一**并集信号集**（post_command/geometry_rebuilt/command_amended/metadata_changed/named_group±：单命令与批执行每步只发 pre/post_command（bus.py:101/115，批成功路径无 _rebuild bus.py:196-235 逐行读证）、undo/redo/重放/回滚恢复只发 geometry_rebuilt（bus.py:165）——只订单一族会漏），订阅者统一收敛到单一 **_schedule_refresh()（QTimer.singleShot(0) 合帧**：同一事件循环轮内多信号只触发一次重建=批执行循环末渲染最终快照，持守 C3）→ 重取 kernel.viewport_data() 重建（同步，A5）；数据获取经 AppServices.kernel（BuildKernel 已实现 ViewportPort）。**平台兜底阶梯（钉死不留判断）**：Linux apt 库后 GL 仍不可用 → xvfb-run 跑 GL 测试（apt 可装；ci.yml 允许编辑——冻结的只是 T1 三 job matrix 边界）；Windows → GL 测试逐测试覆写 QT_QPA_PLATFORM 为 native（conftest 的 setdefault 恰好允许；注：GitHub Actions windows runner 上 native GL 稳定性未证，若 CI 不稳则该子集降级为本地证据+CI 显式 skip 入 F4 呈报——兜底阶梯由此闭环）；残余平台差异=显式 skip 记录进证据并在 F4 呈报，绝不静默。**类型策略**：pyqtgraph/PyOpenGL 无官方 stub → 手写最小 typings/pyqtgraph/pyqtgraph.pyi 与 typings/OpenGL/…（仅覆盖所用 API），pyrightconfig.json 增 "stubPath": "typings" 附理由注释（镜像 pyproject E501/N818 carve-out 先例）；显式拒绝 executionEnvironment 按目录放宽；stub 是声明非抑制——零抑制扫描保持绿。tests/ui/test_viewport.py（offscreen）：喂法兰序列→数据条数=特征数、上屏 item 数=1（仅最终快照）；fit_view 后 camera 参数变化断言；线框切换状态翻转；空文档→零 item。Must NOT：不在 ui import build123d/OCP；core 不动；不做拾取（todo 10）；不做抗锯齿/材质精细调（工业灰蓝底色即可，初稿 §9）。
  Closes: GAP-4（渲染半）
  Parallelization: Wave 3 | Blocked by: 2,3,4 | Blocks: 10,13
  References: 技术路线.md:21-22、:164-173（网格占位决策依据）；todo 2/3 产物（ViewportData/BuildKernel.viewport_data）；pyqtgraph.opengl GLViewWidget/MeshData API（外部文档，可用 librarian 查证 offscreen 行为）；src/mycad/core/signals.py（geometry_rebuilt）；docs/UI设计初稿.md §9（视口底色基调）
  Acceptance criteria: offscreen scoped pytest 绿（三平台 CI 绿——GL 离屏依赖 todo 1 已备的 apt 库）；scoped 四门绿。
  QA scenarios: happy = 法兰序列渲染断言+fit+切换；failure = 空文档零 item；证据记录三平台 GL 各走哪条兜底路径。Evidence `.omo/evidence/task-9-phase1-desktop-shell.md`
  Commit: Y | feat(ui): pyqtgraph mesh viewport with shading/wireframe and fit
  Recommended task executor category: deep-low

- [ ] 10. 颜色编码拾取 + 结构树↔视口双向高亮
  What to do / Must NOT do: 拾取（A9）：按 viewport_data() 快照条目操作——每 ordinal 快照唯一编码色（feature_id→颜色映射表，稳定 hash 生成；**快照语义注意：破坏性命令（boolean_cut）高亮的是其执行后状态，验收按此断言**）；点击时离屏渲染 pass 用编码色画全部 mesh → glReadPixels 反查点击位置 → feature_id → 选中；选中反馈：该 feature mesh 材质高亮（emissive/亮度）+ 结构树对应节点选中（接 todo 7 selectionChanged）；反向：树节点点击 → 视口高亮同一 feature（必要时 fit 到该特征）。tests/ui/test_picking.py（offscreen）：两 feature 场景，模拟点击（直接调拾取函数传已知颜色坐标）→ 选中正确树节点；树选→viewport 高亮标志断言；点空白→无选中。Must NOT：不做框选/多选；不做编辑 gizmo/handle。
  Closes: GAP-4（交互半）
  Parallelization: Wave 3 | Blocked by: 7,9 | Blocks: 13
  References: 草稿 A9（颜色编码拾取决策）；docs/UI设计初稿.md §6（自动跳转表：树↔视口联动规则）；todo 7/9 产物；pyqtgraph.opengl glReadPixels 可行性（offscreen 下读回——若 offscreen 读回不稳定，降级为数学求交拾取（射线×三角形），决策记录进证据文件）
  Acceptance criteria: offscreen scoped pytest 绿；scoped 四门绿。
  QA scenarios: happy = 双向联动断言；failure = 空白点击无选中。Evidence `.omo/evidence/task-10-phase1-desktop-shell.md`
  Commit: Y | feat(ui): color-coded picking with tree<->viewport bidirectional highlight
  Recommended task executor category: deep-low

- [ ] 11. 底栏 CLI Tab（与 session 同源）
  What to do / Must NOT do: 底栏 QTabWidget：「CLI」页 = QPlainTextEdit 输出 + QLineEdit 输入，命令派发复用 src/mycad/cli/session.py 的解析与反馈文案（同 registry/bus/grammar，不复制实现——**扩展 session.execute_line（session.py:276-295 既有单行入口）为纯函数 execute_line(line, *, loaded: LoadedDocument | None, services, on_replace_doc: Callable[[LoadedDocument | None], None]) -> tuple[int, list[str]]**（双审收敛修批）：返回 (rc, messages)，messages 替代 print（print 收敛到 headless CLI 边缘薄壳，GUI Tab 消费同一字符串）；on_replace_doc=换文档回调由调用方注入：GUI Tab 传入 todo 8 生命周期打包（app.new_document/open_document、脏态复位、树/视口/草稿刷新）——session 既有 _cmd_new/_cmd_open（session.py:344-378，静态读证直接替换 self._doc）纯函数化后一律改经该回调；GUI Tab 自身持有 LoadedDocument（不借 session._doc——文档所有权单一定义：headless 时 session 自持、GUI 时 UI 持有）；headless 路径传内部回调保持现行为；改 session 需保 CLI 既有测试全绿）；「Chat」页容器本 todo 先占位（todo 12 填卡片流）。F-AGT-05 同源断言：GUI CLI 执行命令的输出与 headless session 对同一命令的输出一致（白名单差异仅前缀提示符）。tests/ui/test_cli_tab.py。Must NOT：不做自然语言；不另写命令解析器；不绕过确认红线（确认类命令在 GUI 同样走确认——与 session 行为一致即可）。
  Closes: GAP-5（底栏半）、GAP-7（同源半）（双审收敛：on_replace_doc 接 todo 8 生命周期 → Blocked by 增 8）
  Parallelization: Wave 3 | Blocked by: 4,8 | Blocks: 13
  References: src/mycad/cli/session.py（execute_line :276-295、_cmd_new/_cmd_open 直接替换 self._doc :344-378、REPL 主循环与文案）；src/mycad/app.py:101-117（new_document 生命周期语义——on_replace_doc 的 GUI 实现依据）；src/mycad/cli/plans.py（JSON 计划流参考）；src/mycad/commands/grammar.py（ASCII 语法）；tests/cli/ 既有 session 测试（重构后必须保持绿的面）
  Acceptance criteria: offscreen scoped pytest 绿（同源一致性断言）；session 重构后 tests/cli 全绿；scoped 四门绿。
  QA scenarios: happy = 同源一致；failure = 错误命令错误文案一致（负向同源）。Evidence `.omo/evidence/task-11-phase1-desktop-shell.md`
  Commit: Y | feat(ui): CLI tab reusing session dispatch for parity
  Recommended task executor category: unspecified-low

- [ ] 12. 计划卡片 + 六态确认管道
  What to do / Must NOT do: Chat 页=计划卡片流（初稿 §7 交互样例）：左栏双击（todo 6 信号）→ 新建 Plan 草稿（core.plan.Plan）→ 渲染卡片（命令名/参数表/影响对象预览=spec 目标参数）序列；三键：「编辑」→参数对话框（与右栏「选项」Tab 经**同一 PlanDraftController**（todo 6 契约、todo 7 编辑组件）双向同步）；「取消」→plan.cancel()；「执行」→plan.confirm(actor="gui")（非空 actor）→ **bus.execute_batch(plan) 一次调用整批**（Bus 自带快照/mark_executing/mark_done/mark_failed；失败抛 BatchRollbackError，UI 捕获标红卡片，回滚 ordinal 列表取 exc.executed_ids——镜像 cli/session.py:73-77 _print_rollback 与 :548-577 _cmd_end_batch 既有用法）→成功卡片转 done、失败整批回滚+卡片标红+错误文案可见。影响对象=PlannedCommand.affected_object 字面值（AFFECTED_OBJECTS 表，document.py:59-68）——不是 spec 目标参数。草稿编辑=draft 态内改 steps（经 PlanDraftController）；执行后修订（command_amended 信号路径）阶段 1 显式无 UI 入口（属性 Tab 只读），阶段 2 再议。tests/ui/test_plan_confirm.py：六态真实序列往返（draft→confirmed→executing→done/failed/cancelled，core/plan.py:19-31）；非法转换 UI 不可触发（按钮态断言）；回滚场景：两命令计划其一必失败（如 boolean_cut 空目标）→ execute_batch 抛 BatchRollbackError、history 长度不变（零新增）、内核 mass_properties 与批前一致（恢复经 _rebuild，bus.py:224——oracle N10）+卡片标红；正常计划→done+history 恰 2 条；选项 Tab 改参数→卡片参数同步显示。Must NOT：不做 NL 生成；不绕过 plan.confirm 直提 bus；不实现网络 confirmation_token（阶段 2 MCP 落点，本阶段 actor="gui" 即产品侧交互雏形）；不做多计划并行（一次一张活动卡片）。
  Closes: GAP-5（确认半）
  Parallelization: Wave 3 | Blocked by: 6,7 | Blocks: 13
  References: src/mycad/core/plan.py:19-31（六态真实名 draft/confirmed/executing/done/failed/cancelled+合法边+InvalidPlanTransition）、:58-63（confirm(actor) 非空）；src/mycad/core/bus.py:196-235（execute_batch+BatchRollbackError.executed_ids）；cli/session.py:548-577（_cmd_end_batch 流程样例）、:73-77（_print_rollback）；core/document.py:59-68（AFFECTED_OBJECTS/affected_object）；docs/UI设计初稿.md §7（计划卡片交互样例）；docs/需求分析书.md:136-152（§6 确认流产品规则：默认必须确认）；ADR-004:24（confirmation_token 只能来自产品侧用户交互）；src/mycad/cli/plans.py（JSON 计划执行既有流参考）；src/mycad/core/bus.py（批事务快照/回滚语义）
  Acceptance criteria: offscreen scoped pytest 绿（六态/回滚/同步三类断言）；scoped 四门绿。
  QA scenarios: happy = 正常计划 completed；failure = 必败计划整批回滚+卡片可见失败。Evidence `.omo/evidence/task-12-phase1-desktop-shell.md`
  Commit: Y | feat(ui): plan-card confirmation pipeline on the six-state plan machine
  Recommended task executor category: unspecified-high

- [ ] 13. 验收解跳 + 全量回归收口
  What to do / Must NOT do: tests/test_acceptance_flange.py:282-286 的 test_ui_layout_acceptance 去 skip，落地 UI 初稿 §11 五条（五区布局在位/最小工作流=命令库建模→计划确认→导出 STEP/整批撤销（bus.undo(len(plan.steps)) 恢复计划前状态——§8.3「可回退该批计划」的钉死解读，验收断言之）/Toolbar QSettings 记忆/整体离屏可用）；跑全量四门（ruff check/format 全树 + basedpyright + pytest 全量，Linux 本地）；推 CI 三平台全绿。Must NOT：不放宽既有断言；不删既有测试；新增测试全部 offscreen 可跑。
  Closes: GAP-1/10（收口）
  Parallelization: Wave 3 | Blocked by: 5,6,7,8,9,10,11,12 | Blocks: 14
  References: tests/test_acceptance_flange.py:282-286（skip 占位原文）；docs/UI设计初稿.md §11（验收五条）；docs/需求分析书.md:164-172（§8 验收基线）；AGENTS.md COMMANDS（四门命令）与「验证纪律」
  Acceptance criteria: `uv run pytest -q` 全绿（802 既有 + 新增 UI 测试数）；`uv run ruff check .` + `uv run ruff format --check .` + `uv run basedpyright` 全绿；CI 三平台全绿（junitxml 注解零失败项）。
  QA scenarios: happy = 全量四门+CI；failure = 阶段 0 既有测试任何回归即回修（零回归红线）。Evidence `.omo/evidence/task-13-phase1-desktop-shell.md`
  Commit: Y | test(acceptance): unskip ui layout acceptance and close the phase-1 regression gate
  Recommended task executor category: unspecified-high

- [ ] 14. README + AGENTS.md + 文档同步
  What to do / Must NOT do: README 快速开始增 `uv run mycad gui`（附 offscreen 提示：CI/远程桌面场景设 QT_QPA_PLATFORM=offscreen）；AGENTS.md：STRUCTURE 树加 src/mycad/ui/ 行、CODE MAP 加主窗/视口条目、CONVENTIONS「T1 分层硬规则」增 ui 条款（ui 唯一 PySide6 包、ui 禁 build123d/OCP/mycad.geom、ui 允 numpy、tests/ui 进测试白名单）；README:52-54（「尚未开始：PySide6 外壳」行）与 :18（tech-stack 阶段措辞）、pyproject.toml:4（description 的 Phase 0 MVP 字样）、AGENTS.md OVERVIEW 阶段措辞与 CONVENTIONS 测试条款（todo 1 落地后同步文档）；技术路线.md §9 增 PySide6 LGPL 动态链接评估一行注记；docs/UI设计初稿.md 如实现有偏差处加「实现注记」（**改 docs/ 下文件必须同步 tests/test_scope_audit.py 的 hash_tracked_docs 基线**——先跑该测试看红再更新基线）。Must NOT：不写营销文案；不改 ADR-001..005（ADR-006 由 todo 16 改）；不改需求书正文（只允许初稿加注记）。
  Closes: GAP-7（文档半）
  Parallelization: Wave 4 | Blocked by: 13 | Blocks: —
  References: README.md（现行三命令结构）；AGENTS.md STRUCTURE/CODE MAP/CONVENTIONS 节（todo 1 已改过 M1 行——本 todo 是结构/规则行）；tests/test_scope_audit.py:451（hash_tracked_docs docs/ 基线机制）；docs/UI设计初稿.md
  Acceptance criteria: `uv run pytest tests/test_scope_audit.py -q` 绿（基线同步后）；`QT_QPA_PLATFORM=offscreen timeout 30 uv run mycad gui` 冒烟过；scoped 四门绿。
  QA scenarios: happy = 文档一致性+基线绿。Evidence `.omo/evidence/task-14-phase1-desktop-shell.md`
  Commit: Y | docs: gui quickstart, layering rules, and implementation notes
  Recommended task executor category: writing

- [ ] 15. T2 aarch64 QEMU 回归（ADR-006 第 2 条收口）
  What to do / Must NOT do: 产出可复跑脚本（建议 scripts/t2_qemu_regression.sh 或 .py，取实施成本低者）：QEMU（qemu-user 容器路线或 qemu-system aarch64 + Ubuntu 22.04 云镜像路线，二选一并记录理由）内：aarch64 Python 3.12 + uv sync（PySide6/build123d/cadquery-ocp-novtk 的 manylinux aarch64 wheel 可得性实证）+ 全量 pytest（或最小：四门 scoped+全量 pytest，时间盒内跑不完则记录跑到的子集与理由）。本机执行一次，证据写 .omo/evidence/t2-qemu-regression-phase1-desktop-shell.md（QEMU 版本、镜像、命令、输出摘要、结论行=T2 通过/不通过+问题清单）。Must NOT：不改 CI matrix（ADR-006:31-32：阶段 1 CI 仅 T1）；不因 QEMU 慢删测试；不购硬件。
  Closes: GAP-8（T2 半）
  Parallelization: Wave 4 | Blocked by: 1 | Blocks: —（可提前启动）
  References: docs/adr/ADR-006-platform-tiering.md:12（T2 阶段 1 补齐承诺）、:31-32（CI 边界）；.omo/evidence/final-3-phase0-mvp.md §3（阶段 0 T2 wheel 可得性证据）；pyproject.toml pins；AGENTS.md「验证纪律」
  Acceptance criteria: 证据文件存在且含真实运行输出与结论行；脚本 exit 0 可复跑；结论若「不通过」须附问题清单与建议（不阻塞阶段 1 交付，但须在 F4 报告）。
  QA scenarios: happy = 脚本复跑 exit 0 + 证据齐全。Evidence `.omo/evidence/task-15-phase1-desktop-shell.md`（过程）+ t2-qemu-regression-phase1-desktop-shell.md（结论）
  Commit: Y | ci(platform): t2 aarch64 qemu regression evidence and rerunnable script
  Recommended task executor category: unspecified-high

- [ ] 16. T3 龙芯 spike → go/no-go 决议 + ADR-006 更新
  What to do / Must NOT do: 龙芯 loongarch64 探测：pypi.loongnix.cn 镜像上 build123d/cadquery-ocp 系（novtk 变体是否存在）可得性探测 + 若可得跑最小 flange 建模脚本；不可得则源构建 OCCT/OCP 时间盒评估（文献+社区证据，不实际编译超时间盒）；PySide6 loongarch64 wheel 可得性一并记录。产出决议：go=阶段 2 纳入路线/no=降级战略路线并记理由；更新 docs/adr/ADR-006-platform-tiering.md（决议段+日期+证据指针）；**改 ADR 前先读 tests/test_adr_docs.py 的断言并同步**。证据 .omo/evidence/t3-loongson-spike-phase1-desktop-shell.md（探测命令、输出、决议理由）。Must NOT：不实际购硬件；不把 loong 加进 CI（FORBIDDEN_CI_TOKENS 红线）；不在本 todo 尝试源构建超时间盒。
  Closes: GAP-8（T3 半）
  Parallelization: Wave 4 | Blocked by: 1 | Blocks: —（可提前启动）
  References: docs/adr/ADR-006-platform-tiering.md:15（spike 承诺原文：pypi.loongnix.cn+源构建+最坏降级）；tests/test_adr_docs.py:76-81（BLOCKLIST_PHRASES——阶段 0 前缀短语不受影响，但改 ADR-006 正文须过其全部断言）；tests/test_scope_audit.py:391（FORBIDDEN_CI_TOKENS=aarch64/arm64/qemu/loong 禁入 ci.yml——脚本/证据文件不在 ci.yml 内不受限）
  Acceptance criteria: ADR-006 含决议段；`uv run pytest tests/test_adr_docs.py tests/test_scope_audit.py -q` 绿；证据文件在。
  QA scenarios: happy = ADR 断言绿+决议成文。Evidence `.omo/evidence/task-16-phase1-desktop-shell.md` + t3-loongson-spike-phase1-desktop-shell.md
  Commit: Y | docs(adr): t3 loongson go/no-go resolution in ADR-006
  Recommended task executor category: unspecified-high

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
- [ ] F2. Code quality review
- [ ] F3. Real manual QA (agent-run：scripted offscreen GUI walkthrough——菜单→命令库→计划卡片→导出法兰，pytest-qt 驱动，零人工干预)
- [ ] F4. Ideal-state fidelity

## Commit strategy
- **分支**：单一工作分支 `phase1-desktop-shell`，最终单 PR 合入 main，**禁止 main 直推**（A7；阶段 0 收尾的 main 直推偏离已 ledger 记录，本阶段回归 PR 流）。
- 每 todo 一个语义提交，提交前 scoped 四门全绿；提交信息沿用 `type(scope): summary` 风格（见各 todo Commit 行）。
- 每 todo 的证据文件（.omo/evidence/task-<N>-*.md）随该 todo 提交入仓。
- 基础设施故障/根因诊断/重派决策追加 `.omo/start-work/ledger.jsonl`（JSONL，{ts,event,task,detail}）。
- 新文件一律 SPDX 头（Apache-2.0）；ui/ 新文件同。
- CI 三平台全绿是每 todo 关闭的硬条件（junitxml 注解自报告已上线，失败测试名直接出现在 Actions 注解）。
- 不打 tag、不发 release、不做打包。

## Success criteria
> One row per IS row. The plan is complete only when every IS row has a delivering todo and a proving QA scenario; F4 checks the delivered behavior against these rows 1:1, and a shortfall becomes new `- [ ] N.` rows, never a note.
| IS | Delivering todo(s) | Proving QA scenario | Evidence |
| --- | --- | --- | --- |
| IS-1 五区+Toolbar/QSettings | 4, 5, 13 | shell 冒烟五区断言 + toolbar 往返 + 验收 §11 | task-4/5/13 |
| IS-2 左栏命令库 | 6, 13 | 八 P0+插件命令出现/搜索过滤 | task-6/13 |
| IS-3 右栏五 Tab+树 | 7, 10, 13 | 三命令树断言 + 双向联动 | task-7/10/13 |
| IS-4 视口交互 | 9, 10, 13 | 网格渲染/fit/线框/拾取双向 | task-9/10/13 |
| IS-5 Chat 计划卡片 | 11, 12, 13 | 六态往返 + 必败回滚 + 同步 | task-11/12/13 |
| IS-6 文档生命周期 | 8, 13 | 往返一致 + 脏态拦截 | task-8/13 |
| IS-7 CLI/GUI 同源+gui 入口 | 4, 11, 14 | gui 冒烟 + 同源文案一致 | task-4/11/14 |
| IS-8 跨平台收口 | 13, 15, 16 | CI 三平台 + T2 证据 + T3 决议 | task-13/15/16 |
| IS-9 合规守卫迁移 | 1, 14 | layering/scope/notice 绿 + core 注入探针红 | task-1/14 |
| IS-10 headless 零回归 | 13 | 全量 802+ 既有测试绿 + CI 三平台 | task-13 |
