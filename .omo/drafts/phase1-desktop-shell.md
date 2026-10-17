---
slug: phase1-desktop-shell
status: awaiting-approval
intent: clear
review_required: false
pending-action: 批准简报已出，等用户 okay 后写 .omo/plans/phase1-desktop-shell.md
approach: PySide6 桌面壳「壳先行、视口解耦」——新建 src/mycad/ui 为唯一允许 import PySide6 的包（镜像 geom 对 CAD 后端的独占模式）；core 新增 ViewportData 依赖倒置协议、geom 按特征网格化实现；五区布局 + 注册表驱动面板 + core.plan 六态确认管道全部接既有 Bus/Document/SignalBus；守卫（layering/M1）与 NOTICE 同步迁移；T2 aarch64 QEMU 回归 + T3 龙芯 spike 按 ADR-006 收口。
---

# Draft: phase1-desktop-shell

## Affected user and ideal state

- **U1 CAD 最终用户**（工程师/爱好者，首期=项目验收牵引者本人）：今天只有 CLI/REPL/JSON 脚本三种入口；之后获得完整 GUI 法兰工作流（建模→计划确认→导出）。
- **U2 插件作者**：命令经 entry-point 贡献后自动出现在左栏命令库（多入口同源，技术路线 §2 原则 2）。
- **U3 阶段 2 的 Agent/MCP 客户端**：ADR-004 的 confirmation_token「只能由产品侧用户交互产生」——阶段 1 Chat 确认按钮就是该交互的成形落点。
- **U4 维护者/CI**：T1 三平台 CI、分层守卫、NOTICE 持续可信。

<!-- IS-n | property of the ideal state | reason -->
<!-- GAP-n | difference between IS-n and today | reason | closed by todo(s) -->

| 行 | 陈述 | 理由 |
| --- | --- | --- |
| IS-1 | 主窗五区齐全（菜单/Toolbar/左栏/视口/右栏/底栏/状态栏）；Toolbar 可消隐、四边停靠、可锁定、QSettings 记忆恢复 | F-UI-01/02/06 全 P0；UI 初稿 §2-§4 |
| GAP-1 | 无 ui 包、无 gui 入口，全部缺失 | 阶段 0 交付边界是 headless | C1 |
| IS-2 | 左栏搜索+可折叠分类命令库，内容注册表驱动（八条 P0 + 插件贡献自动出现） | F-UI-03 P0；NF-06 注册式扩展 |
| GAP-2 | 命令只存在于 CLI | 同上 | C2 |
| IS-3 | 右栏 结构/属性/选项 三 Tab 常驻可用；显示/测量占位 Tab 在位；结构树按 基准/草图/特征/实体 分组、点击↔视口联动 | F-UI-04、F-TREE-01、F-PROP-01、F-OPT-01 全 P0 |
| GAP-3 | 无任何面板 | 同上 | C2 |
| IS-4 | 视口：旋转/平移/缩放/适应窗口；着色/线框切换；点选特征与结构树双向高亮 | F-MOD-02/03 P0、F-MOD-04 P1（一并做，成本低） |
| GAP-4 | 无视口；且 cadquery-ocp-**novtk** 选型（pyproject.toml:12-14 注释「T1 forbids VTK/PySide6」）使 OCCT AIS 同进程嵌入不可行（Qt5/Qt6 双 Qt 冲突）→ 必须走路线 §1「早期网格预览过渡」+ §8 风险缓解「网格预览占位；接口与最终 AIS 视口互换」 | 技术路线既定缓解路径 | C3 |
| IS-5 | 底栏 Chat\|CLI：Chat 渲染计划卡片（命令名/参数/影响对象），执行/编辑/取消三键；编辑与右栏「选项」Tab 双向同步；确认后才提交 Command Bus；失败整批回滚且 UI 可见 | F-UI-05、F-AGT-02/03/04 全 P0 |
| GAP-5 | 确认管道只存在于 headless CLI（run --json 的确认流） | 阶段 0 边界 | C4 |
| IS-6 | 文档生命周期全 GUI：新建/打开/保存/另存/导出 STEP+STL；未保存变更关闭有提示 | F-DOC-01/02 P0 |
| GAP-6 | 文件操作只在 CLI | 同上 | C1 |
| IS-7 | CLI/GUI 同源：GUI 确认执行的计划在 CLI 有等价命令文案；`mycad gui` 启动入口 | F-AGT-05（P1，复用 grammar 成本低）；多入口同源原则 |
| GAP-7 | 无 gui 子命令 | 同上 | C1 |
| IS-8 | 跨平台收口：T1 三平台 CI 含 GUI offscreen 测试全绿；T2 aarch64 QEMU 回归补齐；T3 龙芯 spike 产出 go/no-go 决议并更新 ADR-006 | ADR-006 第 2/5 条是阶段 1 承诺 |
| GAP-8 | T2 只有 wheel 可得性证据无端到端验证；T3 无 spike | ADR-006:31-32 | C6 |
| IS-9 | 合规与守卫迁移：NOTICE 归属 PySide6+shiboken6 及传递闭包；M1 禁词表改造（PySide6 仅 ui/ 可引）；test_layering 扩展；core 依旧 Qt-free；零 type:ignore 保持 | NF-05；技术路线 §9 |
| GAP-9 | PySide6 目前是 M1 禁词（tests/test_scope_audit.py:29,75）；NOTICE 无 Qt 条目 | 阶段 0 反 GUI 纪律需定向解除 | C5 |
| IS-10 | headless 零回归：CLI/REPL/脚本行为不变，既有 801 测试基线保持绿 | 桌面壳不得侵蚀内核契约 |
| GAP-10 | 引入 GUI 主依赖带来安装面/闭包变化风险 → 由全量基线 + 三平台 CI 守护 | 风险型 GAP | C5 |

## Components (topology ledger)

| id | outcome（一行） | status | evidence |
| --- | --- | --- | --- |
| C1 ui-shell | QMainWindow 五区布局 + 菜单 + Toolbar(QSettings) + 状态栏 + `mycad gui` 入口 + 文档生命周期（新建/打开/保存/导出/未保存提示，单文档窗） | active | UI 初稿 §2/§3/§4/§8/§10 |
| C2 ui-panels | 左栏注册表驱动命令库（搜索+分类折叠）+ 右栏五 Tab（结构/属性/选项常驻，显示/测量占位） | active | UI 初稿 §5/§6；需求 F-UI-03/04 |
| C3 viewport | core ViewportData 协议（依赖倒置）+ geom 按特征网格化实现 + ui 网格渲染（旋转/平移/缩放/fit、着色/线框、点选↔树联动）；渲染库见 Open question Q1 | active | 技术路线 §1/§8；ports.py 模式 |
| C4 plan-confirm | 底栏 Chat/CLI Tab + 计划卡片 + 选项 Tab 参数编辑同步 + core.plan 六态驱动确认管道 + 批事务回滚反馈 | active | 需求 F-AGT-02/03/04；core/plan.py |
| C5 guards-compliance | layering/M1 守卫迁移 + NOTICE 闭包归属 + CI offscreen + README 快速开始 | active | AGENTS.md 分层规则；NF-05 |
| C6 platform-t2t3 | aarch64 QEMU 回归（T2 补齐）+ 龙芯 spike → go/no-go 决议（T3，更新 ADR-006） | active | ADR-006 第 2/5 条 |

## Open assumptions (announced defaults)

<!-- assumption | adopted default | rationale | reversible? -->

| 假设 | 采纳默认 | 理由 | 可逆? |
| --- | --- | --- | --- |
| A1 视口技术路线 | 网格预览占位（非 OCCT AIS 同进程） | 路线 §1「早期可用网格预览过渡」+ §8 风险表；-novtk 与 Qt6 双 Qt 冲突使其成为唯一同进程选项；ViewportPort 接口保持可换 | 是（接口隔离） |
| A2 命令范围 | 现有八条 P0 接 UI，不新增几何命令 | 阶段 1=壳、阶段 3=特征加深（路线 §5）；UI §11 验收只要 P0 可发现入口 | 是 |
| A3 Chat 语义 | 计划卡片确认 UX，无自然语言生成 | ADR-004 阶段边界（LLM=阶段 2）；F-AGT-01 已在阶段 0 显式延期 | 是 |
| A4 窗口模型 | 单文档主窗（新建/打开替换当前文档） | UI 初稿无 MDI；kernel 进程级单例 reset 语义（app.py:107-110） | 是 |
| A5 并发模型 | 同步重建，无工作线程 | core 全家单线程设计（signals.py:5-9、plan.py:5-8 的 phase 0 Must NOT） | 是（阶段 2 再议） |
| A6 依赖位置 | PySide6 进主依赖（非 optional extra） | 未发 PyPI；uv sync 单一安装路径；CI 三 job 直接跑 GUI 测试 | 是（发版前可拆 extras） |
| A7 分支策略 | 回归「单一工作分支 + 单 PR 合入、禁 main 直推」 | plan:528-534 + phase1-backlog.md 流程项 | 否（既有决定） |
| A8 平台任务 | T2 QEMU 回归 + T3 spike 纳入本阶段 | ADR-006 第 2/5 条已承诺 | 否（需 ADR 修订） |
| A9 视口选择实现 | 颜色编码拾取（每个 feature 独立 mesh，glReadPixels 反查） | 依赖 Q1 选库后的通用做法；与 AIS 未来路径不冲突 | 是 |

## Findings (cited - path:lines)

- docs/技术路线.md:21-22（可视化：优先 OCCT AIS 嵌入 Qt；**早期可用网格预览过渡**，视口手感与 UI 壳解耦）、:55-63（ui 模块职责）、:143（仓库 src/mycad/ui/ 布局）、:149（assets/ 图标 QSS）、:157-160（命令/计划协议基线、计划六态）、:164-173（风险表：OCCT 视口嵌入→网格占位缓解）、:178-180（PySide6 归属 NOTICE、不引 GPL/AGPL 主许可）
- docs/需求分析书.md:84-118（F-MOD-01..05 / F-UI-01..06 / F-AGT-01..06 / F-TREE-01 / F-PROP-01 / F-OPT-01 优先级表）、:122-133（NF-01..07）、:136-152（§6 确认流产品规则：默认必须确认、视图类操作可不经确认）、:164-172（§8 验收基线五条：法兰参数化建模/Chat 计划确认导出 STEP/撤销回退/主窗布局/LICENSE+NOTICE）
- docs/UI设计初稿.md §2（五区布局图+区域职责+刻意换位：结构树在右栏）、§3（菜单七项）、§4（Toolbar 消隐/换边/锁定/QSettings/最小图标 12-17）、§5（左栏交互+分类+**5.3 命令清单表含 P0/P1/P2**+register_left_item 扩展约定）、§6（右栏五 Tab+结构树分组+自动跳转表+register_right_tab）、§7（底栏 Chat|CLI+计划确认交互样例+伸缩+register_bottom_tab）、§8（状态栏）、§9（工业灰蓝 QSS）、§10（PySide6 部件建议：QMainWindow/QToolBar/QDockWidget|QSplitter/QTabWidget/QSettings）、§11（UI 首期验收五条）
- docs/adr/ADR-004-mcp-boundary.md:17-18,24（阶段 0 零 mcp/LLM/网络依赖；F-AGT-01 与 A19 显式延期；阶段 2 才是 Agent 闭环；confirmation_token 只能来自产品侧用户交互）
- docs/adr/ADR-006-platform-tiering.md:12（**T2 aarch64 实机/QEMU 回归在阶段 1 补齐**）、:15（T3 龙芯阶段 1 末 spike 做 go/no-go：pypi.loongnix.cn 镜像+源构建 OCCT/OCP，最坏降级战略路线）、:31-32（CI 阶段 0/1 仅 T1 三 job）
- src/mycad/app.py:36-49（AppServices 恰四成员：registry/kernel/formats/plugins；Document/Bus 故意不入）、:101-117（new_document 装配 handler map + kernel.reset 独占；confirmed_by 前瞻参数）、:10-11（multi-document kernel sessions 标注为 Phase 1 direction——本计划以单文档窗响应，多窗 MDI 不做）
- src/mycad/core/signals.py:20-30（九信号：pre_command/post_command/command_amended/metadata_changed/named_group_added/removed/document_saving/document_saved/geometry_rebuilt）、:68-108（SignalBus：weak 订阅、listener 异常隔离为 RuntimeWarning、单线程）
- src/mycad/core/plan.py:19-31（PlanStatus 六态恰六条合法边；非法转换抛 InvalidPlanTransition）、:58-63（confirm(actor) 要求非空 actor——GUI 确认按钮的落点）
- src/mycad/core/kernel_protocol.py:16-26（Kernel Protocol 仅 reset/apply——视口需要第三个依赖倒置协议）
- src/mycad/core/ports.py:21-42（ExportableKernel：mass_properties/export_step/export_stl——geom 已有 BRepMesh 网格化能力证明，STL 导出路径在用）
- src/mycad/builtin_commands/specs.py:27-167（八条 P0：feature.box/cylinder/extrude/revolve/hole/hole_pattern + modify.fillet/boolean_cut）
- src/mycad/cli/session.py、src/mycad/cli/plans.py（REPL 与 JSON 计划执行——底栏 CLI/Chat 复用面）
- tests/test_acceptance_flange.py:282-286（test_ui_layout_acceptance = pytest.skip("phase 1: PySide6 shell")——本阶段必须落地解跳）
- tests/test_scope_audit.py:29,75（"PySide6"/"pyside6" 在 M1 禁词表）、tests/core/test_signals.py:99（bad set 含 PySide6/PyQt 系——core 信号抽象禁 Qt 的守卫）、tests/test_adr_docs.py:76-81（BLOCKLIST_PHRASES 是「阶段 0 实现 PySide6」等前缀短语——阶段 1 实现不受限）
- pyproject.toml:15-18（runtime deps 仅 build123d+cadquery-ocp-novtk；:12-14 注释 T1 forbids VTK/PySide6/CadQuery——需随阶段 1 改写）、:23-34（dev 组无 pytest-qt）、:46-55（pytest addopts -ra --ignore=tests/typing）、:87-95（E501/N818 既有 carve-out）
- .omo/plans/phase1-backlog.md（阶段 0 移交的缓办项：镜像 uv.lock 守卫、plugins 空输出、分支策略、PT/PL、守卫机器化 M1/M3/M7/M8-12/M13-14/M17-19/M25、N1/N2、NOTICE 平台人工确认）

## Decisions (with rationale)

- D1 视口 = 网格预览占位，ViewportData 协议隔离（技术路线 §1/§8 既定缓解；-novtk+Qt6 双 Qt 冲突下的唯一同进程解）。
- D2 `src/mycad/ui/` 为唯一允许 import PySide6 的包，镜像 geom 独占 CAD 后端的分层模式；core 新增 ViewportData Protocol（第三个依赖倒置，模式同 ports.py）。
- D3 确认管道直接驱动 core.plan.Plan 六态；`plan.confirm(actor="gui")` 是 ADR-004 confirmation_token 的产品侧交互雏形（阶段 2 MCP 复用同一按钮）。
- D4 左栏命令库 = CommandRegistry.list_by_category() 数据驱动（插件贡献经 app.py:_handler_map 同源出现）。
- D5 GUI 测试跑在 QT_QPA_PLATFORM=offscreen，进 T1 三平台 CI（Windows/Ubuntu 皆可 headless）。
- D6 提交策略回归 PR 流（plan:528-534；阶段 0 收尾 main 直推偏离已 ledger 记录，不再重复）。

## Scope IN

C1-C6 全部组件；UI 初稿 §11 验收五条；需求 §8 基线第 1/3/4/5 条的 GUI 面向收口（第 2 条的 Chat 自然语言部分按 ADR-004 留阶段 2，计划卡片确认部分本阶段完成）；T2 QEMU 回归 + T3 龙芯 spike 决议。

## Scope OUT (Must NOT have)

- 无任何 LLM/MCP/网络代码；无自然语言→计划解析（ADR-004：阶段 2）。
- 不新增几何命令（P1/P2 id 不实现、不注册；保留 id 命名空间规则照旧）。
- 不做多文档/MDI/多窗；不做工作线程/异步重建。
- 不做装配、工程图、草图约束（需求 §3.2 Out + 阶段 3）。
- 不改 .mc.json v1 schema、不动 build123d/OCP 版本 pin（-novtk 保持）。
- core/ 不引 PySide6/Qt（signals.py 抽象即为此设计）；ui/ 不引 build123d/OCP（视口数据走协议）。
- 不做 AppImage/Flatpak 打包（路线 §4：开发期不以打包为阻塞）。
- 不做 Node-RED 流程画布、Kivy、Electron（需求 §3.2 + 路线 §10）。
- 不为单文件加 ruff per-file ignore；零 type:ignore 纪律保持。

## Resolved questions (answered by owner)

- Q1 视口渲染库 = **pyqtgraph.opengl**（用户选定推荐项，2026-10-12）：最轻（纯 Python + PyOpenGL，无 ~90MB VTK wheel）、MIT/BSD 双许可 NOTICE 增量小、占位性质契合阶段 3 换 OCCT AIS 的接口互换承诺；代价 = 颜色编码拾取自写 ~百行（A9 已含）。
- Q2 UI 测试策略 = **随每个 todo 写测试**（用户选定推荐项，2026-10-12）：pytest-qt + QT_QPA_PLATFORM=offscreen 进 T1 三平台 CI；零人工验证不变量保持，沿用阶段 0 每步 scoped 四门纪律。

## Approval gate
status: approved

## Handoff notes (post dual review, 2026-10-12)

双审收敛完成（Momus=APPROVE-with-notes / Oracle=REJECT→2 BLOCKING 修毕）：8 处修批已edit进计划（信号并集订阅+合帧、todo 11 on_replace_doc 签名+依赖 4,8、Windows GL caution、todo 12 mass_properties 断言）；结构自查复过（16+4 行首/16 category）。教训存档：ark-coding-plan glm-5.3 月配额本月耗尽（reset 2026-10-25），fallback 链 minimax-cn/MiniMax-M3 两次实证可用；bg id 不跨重启，评审/派发结果必须当轮取回。

执行者开工第一批动作（AGENTS.md ledger 纪律）——将下行追加至 .omo/start-work/ledger.jsonl：

{"ts":"<填 date -Iseconds>","event":"phase1-plan-dual-review-converged","task":"phase1-desktop-shell 计划双高精度评审收敛","detail":"重派双审（Momus bg_4d3fdb81=APPROVE-with-notes 0b1n、Oracle bg_58226a83=REJECT 2B+7N，均 attempt1 死于 ark glm-5.3 月配额→attempt2 落 minimax-cn MiniMax-M3；v1 输出因幻影 session DB 0 行丢失，经 /tmp/opencode/review-recovery DB 提取器救回孤本发现）。修批 8 处：①oracle B1 主会话读 bus.py 独立证实 execute_batch 成功路径全程无 _rebuild（bus.py:196-235）而 execute 单命令只发 pre/post（:101/:115）——todo 5/8/9 改 post_command+geometry_rebuilt+command_amended+metadata_changed+named_group± 并集订阅，todo 9 加 _schedule_refresh() QTimer.singleShot(0) 合帧；②todo 11 换 Momus execute_line(line,*,loaded,services,on_replace_doc)->(rc,messages) 签名+_cmd_new/_cmd_open 经回调+GUI 自持 LoadedDocument+References session.py:344-378/app.py:101-117+Blocked by 4,8；③todo 9 Windows native GL 于 GH Actions 未证注记；④todo 12 回滚断言增 mass_properties 与批前一致（bus.py:224）。N1-N5 验为 SOUND。结构自查复过 16+4。"}
<!-- 2026-10-12 两问已答（均选推荐）；批准简报（9 默认+2 已决分叉）已出；用户 2026-10-12 回复「okay」= 批准生效。okay 只授权写 .omo/plans/phase1-desktop-shell.md，不授权实现。 -->
