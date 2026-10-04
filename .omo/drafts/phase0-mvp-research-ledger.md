# Draft: phase0-mvp（MyCAD 阶段 0 可编程 MVP 规划）

| 项 | 值 |
|----|----|
| slug | `phase0-mvp` |
| intent | UNCLEAR（bootstrap：用户要求"头脑风暴+规划"，结果粒度未定义） |
| planner | Prometheus (ulw-plan) |
| status | research-done → awaiting-approval（librarian 通道在本环境普遍 30min 零产出挂死，9 车道全部取消；E1–E10 + 安装/法兰尖刺均由规划师直查一手源完成，见 §5） |
| 日期 | 2026-09-17 |

## 0. 用户请求（原文）

"请阅读本项目的初始文档，并展开头脑风暴，做本项目的规划"

补充要求（2026-09-17 第二条消息，原文要点）：
1. 可扩展性：预留 PLM 和 CAE 扩展接口；MCP；插件生态。
2. 可转换主流 CAD 格式文档。
3. 跨平台：支持 Windows；同时考虑国内信创要求。

处理原则：三点均上升为架构级组件 C7/C8/C9；阶段 0 只交付**接缝 + ADR + 最小可验证实现**，不展开生态/适配工程（R12）。

已读基线：`docs/需求分析书.md` v0.1、`docs/技术路线.md` v0.1、`docs/UI设计初稿.md` v0.1。
仓库状态：零应用代码；仅有 docs/、LICENSE、NOTICE、README.md。不是 git 仓库。

## 1. 规划边界默认（可在审批门否决）

- 产出**一份决策完备的阶段 0（可编程 MVP）可执行工作计划**（`.omo/plans/phase0-mvp.md`），因为阶段 0 是纯 Python/headless、无 UI 风险、且是后续一切的地基。
- 阶段 1（桌面壳）、2（Agent 闭环）、3（特征加深）在计划中只给**路线图里程碑与接口契约锚点**，不展开成 todo（跨四阶段写 50+ todo = 不可执行空想）。
- 阶段 0 以需求书 §8 的**法兰验收件**为牵引（外径/内孔/厚度/均布孔），无 UI 全链路打通：
  命令 schema → 校验 → Command Bus（Undo/批事务）→ Document（特征历史）→ geom(build123d/OCP) → STEP/STL；外加 CLI 文本前端与 JSON 文档存取。

## 2. 本机环境事实（已核查 2026-09-17）

- Ubuntu **24.04.4 LTS** noble（基线写"22.04+"，24.04 满足）
- 系统 Python **3.12.3**（E1 已确认：build123d 0.11.1 + cadquery-ocp-novtk 均有 cp312 wheel）
- 有 `uv`（~/.local/bin/uv）；**无 conda/mamba/micromamba**；无系统 OCCT 包（dpkg 无 libocct）→ pip+uv 主路径与本机现状天然匹配，无需装 conda
- 会话 **X11**（非 Wayland；阶段 1 视口的 Wayland 风险在本机暂不暴露，但 CI/用户仍需验证）
- 15 GiB RAM，4 核
- 项目不在 git 版本控制下（阶段 0 首个 todo 需 git init）

## 3. TOPOLOGY LOCK — 独立成败组件（每个 todo 必须回溯其一）

| # | 组件 | 阶段 0 成败含义 |
|---|------|----------------|
| C1 | 环境与打包骨架 | **pip + uv（首选，证据见 §5 L1）**：build123d 0.11.1 经 PyPI 分发、依赖 cadquery-ocp-novtk 预编译 wheel 覆盖 linux-x64/win-x64/linux-aarch64/osx；pyproject src 布局 + pytest + CI 三 job（ubuntu-22.04/ubuntu-24.04/windows-latest）可复现；conda 降级为备选路径（conda-forge 滞后在 build123d 0.9.1） |
| C2 | geom 适配层 | build123d 封装：原型体/布尔/拉伸旋转/孔/阵列/圆角；STEP/STL I/O；形状查询（选择器/几何谓词）；不向上层泄漏 OCP 细节 |
| C3 | 命令模型与注册表 | 每条命令：稳定 id、JSON Schema 参数、CLI 文本映射、validate()、对 Document 的执行语义；注册表驱动左栏/Agent/CLI 三入口同源 |
| C4 | Document + Command Bus | 特征历史为真相源；undo=移除命令+重放；批事务（失败整体回滚到快照）；脏标记/重建信号；JSON 存档格式 v1（含版本迁移钩子） |
| C5 | CLI 前端 | REPL + 脚本文件；命令文本 ⇄ JSON 等价；历史、回放、退出码；headless 可跑（验收：脚本生成法兰并导出 STEP） |
| C6 | 质量与验收资产 | 法兰 golden 件（几何断言：体积/包围盒/孔数）、导入导出往返测试、评测样例目录雏形（为阶段 2）、Apache-2.0 合规（NOTICE/第三方归属） |
| C7 | 扩展架构缝（插件/MCP/PLM/CAE） | 阶段 0 只**设计缝、不实现生态**：core 信号总线、注册表 API 版本化（commands/formats/…）、entry-point 插件清单约定、MCP server 形态可行性结论；PLM=文档元数据字段+事件钩；CAE=几何查询/可调弦差 tessellation/命名组。防后期改造 |
| C8 | 格式互操作矩阵 | geom 内 `FormatProvider` 注册表缝（import 分级：哑实体/装配带属性/可编辑特征——原生格式永不可编辑）；阶段 0 实现 STEP+STL；矩阵结论决定路线图顺序（IGES/DXF/glTF/3MF… 与商业墙 x_t/sat/sldprt/JT） |
| C9 | 跨平台与信创策略 | 分层平台矩阵 Tier1 Ubuntu x64 + Win10/11 x64；Tier2 麒麟/统信 aarch64（鲲鹏/飞腾）；Tier3 龙芯 LoongArch（源构建 OCCT，go/no-go 待证据）。阶段 0 落实：纯可移植代码 + CI 三 job（ubuntu-22.04/ubuntu-24.04/windows-latest）+ 路径/中文/编码纪律；打包后置 |

## 4. Open-assumptions 台账（最佳实践默认，待证据收敛/审批门否决）

| # | 假设默认 | 理由（待证据） | 可逆性 |
|---|----------|----------------|--------|
| A1 | 几何 API 选 **build123d 0.11.1**（Apache-2.0，源自 CadQuery 重构；CadQuery 不进运行依赖，geom 适配层保留互换可能） | PyPI README/包元数据；代数模式选择器利于 Agent；活跃（v0.11.1 2026-07）但仍 0.x 无 1.0 承诺 → 精确 pin | 中：geom 层隔离后可换 |
| A2 | ~~conda 主路径~~ **改为 pip + uv 主路径**：`uv venv` + `uv pip install "build123d==0.11.1"`（拉入 cadquery-ocp-novtk 7.9.3.1.1 = OCCT 7.9.3 无 VTK 预编译 wheel）；conda environment.yml 仅作离线/企业网备选 | **已验证 2026-09-17**：PyPI build123d README 明示 "pip recommended for most users"；OCP wheel 五平台齐全；conda-forge build123d 滞后至 0.9.1（pin ocp 7.8） | 高：只改环境文档 |
| A3 | Python 版本 **3.12**（本机 3.12.3 直接可用） | **已验证**：cadquery-ocp-novtk 7.9.3.1.1 wheel 覆盖 cp310/311/312/313/314；build123d requires-python >=3.10,<3.15 | 高 |
| A4 | Undo 语义 = **删命令 + 历史重放**（不实现 per-command inverse）；批失败 = 快照回滚 | 几何完全可由历史重建；比补偿命令简单可靠 | 中：Bus 接口预留 inverse 扩展 |
| A5 | 存档格式 = **JSON（元数据+有序命令）**，brep 不内嵌 | 可审计/可 diff/Agent 友好 | 中：格式带 version 字段可迁移。**#round10-NB6 计划覆盖更新**：原括注"导入 STEP 作为哑实体节点，v1 只读引用路径"已被计划废止——阶段 0 无任何导入型历史节点（F-DOC-03=P1 属基线自身分期，STEP 读仅 tests/helpers 测试用途）；document.import_step/imported_solid 为阶段 1 演进口，见 ADR-002/ADR-005 |
| A6 | 拓扑引用纪律：命令参数**禁止裸索引**引用面/边；用几何谓词（"最大 Z 平面""孔圆柱面"）+ 基准命名 | TNP 缓解，阶段 0 就要立规矩 | 高 |
| A7 | 阶段 0 **无 LLM 依赖**：agent 包只留协议占位（Plan 数据结构、状态机 draft→…），不接真实模型 | 无网络降级原则；先固定命令契约 | 高 |
| A8 | 阶段 0 **无 Qt 依赖**；可视化仅可选导出 STL/截图脚本，不装 PySide6 | 与"阶段 0 无壳"一致，降低 C1 风险 | 高 |
| A9 | 项目许可证 Apache-2.0；所有新文件带 SPDX 头；NOTICE 维护第三方归属 | NF-05 | 高 |
| A10 | CLI 命令语言用 **ASCII 英文**（`cylinder d=80 h=8`），UI 中文 | 脚本可移植/可回放；技术路线 §7 | 高 |
| A11 | 代码质量：ruff + basedpyright（或 pyright）+ pytest；严格类型，无 any | 现代 Python 栈纪律 | 高 |
| A12 | git init + GitHub Actions（**三 job 矩阵：ubuntu-22.04 + ubuntu-24.04 + windows-latest**（四轮 Momus 裁决统一，全文无"双平台/双矩阵"表述）；`astral-sh/setup-uv` + `uv sync`，pip wheel 直装 OCP 无需 miniconda；aarch64 用 QEMU/或后续伙伴 runner，阶段 0 不门控） | 零代码起步即规范化；Windows 从第一天进 CI；E1 证明 pip 路径三平台可用 | 高 |
| A13 | 扩展机制用 **importlib.metadata entry points**（组名 `mycad.commands` 等 + manifest: id/version/api_version/permissions）；headless 核心插件不依赖 Qt | 2026 Python 标准机制，FreeCAD Workbench/Blender addon 验证过生态模式 | 中：契约 1.0 前可改 |
| A14 | **MCP 定位：MyCAD 作为 MCP server**（stdio 起步），工具即 Command Bus 只读+计划面（list_commands/make_plan/validate_plan/**confirm_execute**/query_document/export）；外部 AI 也必须走确认门；阶段 0 仅出**架构决策记录(ADR)与接口草图**，不实现、不装 mcp 依赖。**E3 修订**：`make_plan` 返回显式 `plan_id` 句柄（规范无协议会话）；确认= `confirm_execute(plan_id, confirmation_token)`，token 只能由用户交互产生，LLM 无法自造；落地时在 SDK v2（`MCPServer`，2026-07-28 规范）/v1 间锁主版本，优先用规范原生 elicitation 承载确认交互 | MCP 是 Agent 互操作趋势；2026-07-28 规范明文要求敏感操作人工确认；确认规则是产品红线不能因远程客户端绕过 | 高：阶段 2/3 落地 |
| A15 | PLM 缝阶段 0 仅预留：Document metadata（part_no/revision/material/source）+ pre/post command & save 事件；不做检入检出/BOM 服务 | PLM 集成全部以元数据+导出件为基础 | 高 |
| A16 | CAE 缝阶段 0 仅预留：mass properties 查询、可调弦差 tessellation、命名选择组（NamedGroup 作为文档对象）；mesher(gmsh/netgen) 与 INP 导出后置（注意 gmsh 许可证评估） | 仿真预处理只需要这些抽象 | 高 |
| A17 | 格式提供方用注册表接口（**E10：对齐 OCCT 7.8 DE_Wrapper 的 FormatName×VendorName provider 模型**，统一 Parameters、shape/XCAF 两级目标）；**免费优先序列全部由 OCCT 开源模块或已自带依赖覆盖**：STEP AP242/STL/BREP→IGES/glTF/OBJ/PLY→3MF(lib3mf 自带)→DXF(ezdxf 1.4.4 自带，**DWG 无免费合规写**，ODA 转换器不可再分发)；JT/Parasolid(x_t)/ACIS(sat)/sldprt/NX/CATIA 经**商业适配插件**（**E5：ODA 会员制无席位费对桌面产品更友好；CAD Exchanger 按席位季度计费**；均不可随 Apache 核心分发，集成商持证自装） | 避免授权墙污染 Apache 核心；插件自装模式；import 三级（哑实体/带装配属性/可编辑——外部格式永不可编辑） | 高 |
| A18 | 平台分层（**E2/E9 精确化**）：T1 Ubuntu 22.04/24.04 x64 + Windows 10/11 x64（CI 三 job 全过，pip wheel 直装，尖刺已证 x64）；T2 麒麟 V10 SP1+（glibc 2.31+）/统信 UOS Server 20/麒麟 V11 on 鲲鹏/飞腾 aarch64——manylinux_2_31 aarch64 wheel 直装，伙伴实机+QEMU CI 回归；**UOS V20 桌面版(glibc 2.28)列为已知不支持基线**；海光/兆芯 x86 归 T1/T2 同栈；T3 龙芯 LoongArch=源构建 OCCT/OCP + 龙芯 PyPI 镜像 + QEMU CI（CPython3.12 原生支持，PyPI 官方 wheel 通道未开），阶段 1 末出 spike 做 go/no-go；申威不纳入 | 信创是用户明确补充；证据见 E2/E9 | 战略层可逆，T3 可能明确降级声明 |
| A19 | 国产环境的 LLM 路径与信创协同：云端国内 API（DeepSeek/通义）或本地 Ollama(aarch64 可行)；不绑境外 API | 信创网络/合规环境 | 高 |
| A20 | 阶段 0 交付物含 **docs/ 新增 ADR 集**：ADR-001 命令/总线、ADR-002 存档格式、ADR-003 扩展点与插件 API 版本策略、ADR-004 MCP 边界、ADR-005 格式提供方分级、ADR-006 平台分层 | 架构缝从第一天留痕，供阶段 1+ 扩展者依据 | 高 |

## 5. 证据台账（研究车道 → 结论，待回填）

| lane | bg task | 状态 | 关键结论 | 验证动作 |
|------|---------|------|----------|----------|
| L1 build123d 生态 | bg_100b15c9/bg_21f7b51b 超时取消 | done(E1+尖刺) | pip+uv 主路径成立且本机实证；build123d 0.11.1 + cadquery-ocp-novtk 7.9.3.1.1(OCCT 7.9.3) 五平台 wheel cp310-314；Apache-2.0；0.x 需精确 pin；自带 ezdxf 1.4.4/lib3mf 2.5.0 | PyPI/GitHub/anaconda API + 本机 uv 安装 + 法兰尖刺（2026-09-17） |
| L2 OCCT 视口/PySide6 | bg_2f48932b 超时取消 | done(E7) | pythonocc-core master 已支持 PySide6（Linux 强制 XCB）但绑定独立 pythonocc-nucleus OCCT，与 cadquery-ocp 是**两套运行时不可同进程混用**（R15）；VTK QVTKRenderWindowInteractor 原生支持 PySide6 → 网格预览路线稳 | tpaviot/pythonocc-core 源码、issue #1421、Kitware/VTK 源码（exa 2026-09-17）|
| L3 TNP/命名 | bg_3d78bc26 | done(E4) | FreeCAD 1.0 启用 realthunder V1 但官方称"缓解非解决"，V2 算法 PR #31040 2026-06 仍 draft；四条抗脆弱路径中"语义选择+建模即代码+datum"正是 A6 → 谓词纪律获权威背书 | FreeCAD wiki/docs、PR #31040、devtalk、Ondsel 博客（exa）|
| L4 LLM 计划/沙箱 | bg_d5bbcb52 | done(E8) | Ollama v0.5+ JSON Schema→GBNF 约束解码（语法合法有保证、值语义仍须校验）；llama.cpp tool_calls 同保证 schema 合规；纪律=小工具面+native tool template+schema 约束+Pydantic 校验+修一次即止 | Ollama 文档、ollama#6002、llama.cpp#9639、2026 实测指南（exa）|
| L5 Command/存档/打包 | bg_f536a876 | done(E6) | FreeCAD .FCStd=zip(Document.xml 参数 + 每对象 .brp 几何快照免重算 + .brp2 ElementMap)；undo=Transaction 栈带名分组/跨文档事务 ID；MyCAD v1 纯命令历史+重放更轻量，brep 快照/命名映射留作演进口（大模型重放性能） | FreeCAD Document.cpp 源码、wiki File_Format_FCStd、DeepWiki、SourceDoc（exa）|
| L6 插件/MCP/PLM/CAE 缝 | bg_482851aa | done(E3) | **MCP Python SDK 已发布 v2 稳定线**（对齐 2026-07-28 规范；FastMCP→MCPServer；pip install mcp=2.x，锁版策略需要）；规范原生 elicitation（工具内暂停向用户要确认 InputRequiredResult/多轮往返）+明文要求敏感操作人工确认；无协议会话→跨调用须显式 plan_id 句柄。PLM/CAE 维持 A15/A16 缝设计 | github modelcontextprotocol/python-sdk、2026-07-28 规范 tools 页、迁移指南（exa）|
| L7 CAD 格式互操作矩阵 | bg_e987fc4a | done(E5+E10) | OCCT 开源免费 RW：STEP AP203/214/AP242、IGES≤5.3、glTF2、OBJ、STL、PLY、VRML、BREP、XCAF；**JT/Parasolid(x_t)/ACIS(sat) 是 OCCT 商业附加组件**；OCCT 7.8 DE_Wrapper 统一 FormatName/VendorName provider 注册表=FormatProvider 缝的对齐样板；商业内核：CAD Exchanger（开发费+**按终端席位季度分发费**）vs ODA（公司年会费、MCAD SDK **无席位费**、Core 会员已含 STEP/IGES/**JT**/QIF）。两者均不可随 Apache 核心再分发 | cadexchanger.com pricing、opendesign.com MCAD SDK、dev.opencascade.org DE_Wrapper/7.8 overview（exa）|
| L8 Windows+信创平台 | bg_525e5ce4 | done(E2+E9) | glibc 精确矩阵（见 E2）：UOS V20 桌面(D版,Debian10) **2.28 明确不满足 manylinux_2_31**；麒麟 V10 SP1/SP3(Debian11) 2.31+麒麟补丁可直装；UOS 服务器 E 版(openEuler)~2.34、麒麟 V11 ~2.35+ 无压力。龙芯：PyPI 官方拒收 loongarch64 wheel（PEP 流程 2026-01 仍在讨论），CPython 3.12 原生支持 triplet，龙芯/社区自有镜像（pypi.loongnix.cn 按 glibc 2.28/2.38 分源、mirrors.loong64.com，社区 CI 已构建 cadquery-vtk）→ T3=源构建 OCCT+镜像+QEMU CI，可行但自费，维持 go/no-go | CSDN 实战、华为支持文档、lindexi 实测、docs.loongnix.cn、discuss.python.org#105548、Loongson-Cloud-Community/pypi（exa）|

### E1（一手源，2026-09-17 webfetch/curl 自查）

- **build123d 最新 v0.11.1，发布 2026-07-02**；GitHub releases API（tag v0.11.1，target dev）；活跃维护（0.10.0 2025-11、0.11.0 2026-06）。仍 0.x，无 1.0 稳定承诺。Apache-2.0。Python `>=3.10,<3.15`（README badge：3.10|3.11|3.12|3.13|3.14）。
- **PyPI 官方安装建议**（PyPI README 原文）："Installing build123d from `pip` is recommended for most users"。
- **0.11.1 运行依赖**（PyPI requires_dist）：`cadquery-ocp-novtk>=7.9,<8.0`、numpy>=2、anytree、ezdxf>=1.1、ipython>=8、ocpsvg>=0.6、ocp_gordon、trianglesolver、sympy、scipy、scikit-learn、webcolors、requests、lib3mf（非 linux-aarch64；linux-aarch64 改依赖 `py-lib3mf` —— 上游已显式处理 aarch64）。viewer（ocp_vscode）是 extra，核心不带 VTK/Qt。
- **OCP wheel 平台矩阵（决定性）**：cadquery-ocp-novtk 7.9.3.1.1（= OCCT 7.9.3 绑定）对 cp310/311/312/313/314 各提供：macosx arm64、macosx x86_64、**manylinux_2_31_aarch64**、**manylinux_2_31_x86_64**、**win_amd64**。无 loongarch wheel。
  - → T1（Ubuntu x64 / Win x64）pip 直装成立；T2（鲲鹏/飞腾 aarch64）有官方 wheel，**但 manylinux glibc≥2.31**：麒麟 V10（glibc 2.28）可能不满足 → 需 L8 核实旧系统方案（统信 UOS 较新版本 glibc 2.31+ 可能直接可用）；T3 龙芯仍无源外二进制，go/no-go 不变。
- conda-forge：build123d 仅到 **0.9.1（2026-05 最后构建）**且 pin `ocp>=7.8,<7.9`，明显滞后 PyPI → conda 不作主路径。conda-forge `ocp` 包本身覆盖 linux-64/win-64/osx-64/osx-arm64/**linux-aarch64**（无 loongarch64）。
- build123d README 已给数据交换习语：`import_step(...)`、`export_step(obj, path)`、`export_stl(obj, path)`、`import_svg(...)`；选择器习语 `part.faces().group_by(Face.area)[-1].sort_by(Axis.X)[-1]`、`.filter_by(GeomType.CYLINDER)`、`fillet(...)`、`chamfer(...)`、`CounterSinkHole`、`GridLocations/PolarLocations`（完整 API 清单待 bg_21f7b51b 补 docs URL）。
- CadQuery conda 最新 2.8.0 用 ocp 7.9.3 + trame/vtk viewer，体量大 → 不进 MyCAD 依赖，仅作 geom 层回退备选记录。

### E2（信创 glibc 精确矩阵，exa 多源 2026-09-17）

| 系统/版本 | 基座 | 实测 glibc | OCP manylinux_2_31 aarch64 wheel |
|---|---|---|---|
| 统信 UOS V20 桌面 D 版 | Debian 10 | **2.28** | ❌ 不可直装 |
| 银河麒麟 V10 SP1/SP2/SP3（含鲲鹏 2403） | Debian 11 | **2.31** + 麒麟补丁（实测 `Ubuntu GLIBC 2.31-0kylin`） | ✅ 可直装（须 CI 实机/容器回归） |
| 统信 UOS Server 20 E 版 | openEuler | ~2.31–2.34 | ✅ |
| 银河麒麟 V11 | 更新基座 | ~2.35+ | ✅ |
| 海光/兆芯 x86_64 | 同上 | 随发行版 | ✅ manylinux x86_64 |

旧版（UOS V20 D / 早期麒麟）缓解路径：基于系统 OCCT 源构建、容器分发、升级到 V11/UOS E。ADR-006 锁定"支持基线=glibc≥2.31"，旧系统列为已知限制。
另：申威 SW64 生态"基本不可行"，明确不纳入。

### E3（MCP，exa 官方源 2026-09-17）

- 官方 Python SDK **v2 为当前稳定线**，支持 **2026-07-28 规范**；`pip install mcp` 现在装 2.x（`FastMCP`→`MCPServer`，`mcp.server.fastmcp`→`mcp.server.mcpserver`，httpx→httpx2，sync handler 改 worker 线程）；v1.x 只在 `v1.x` 分支收关键修复。→ 阶段 2+ 落地时须显式版本决策（pin `mcp>=2,<3` 或 `<2`），**阶段 0 不引入依赖，只出 ADR-004**。
- 2026-07-28 规范 tools 页明文：客户端 SHOULD 对敏感操作弹确认；servers MUST 校验所有输入；**servers MAY 返回 `InputRequiredResult` 走多轮往返（elicitation）在工具执行中暂停索要输入**（`requestState` 显式状态句柄）。
- 规范明确"MCP 无协议级会话，跨调用状态（事务/购物车）必须由创建工具返回显式 handle、后续调用携带"。→ A14 修订：`make_plan` 返回 `plan_id` 句柄，`confirm_execute(plan_id, confirmation_token)` 必须带用户交互产生的令牌，LLM 无法自行构造确认；query/make_plan 只读。
- stdio 与 Streamable HTTP 均为内置 transport；stdio 最贴合本地优先。

### E4（TNP，exa FreeCAD 一手源 2026-09-17）

- FreeCAD 1.0 默认启用 realthunder Linkstage3 拓扑命名 V1；官方 wiki 与核心贡献者坚持称"**缓解（mitigations/improvements），不是解决**"：算法三目的=①在断裂点**报错识别**（最重要）②高置信时给候选修复③更高置信时自动修复且宁可不修；dress-up（圆角/倒角）不自动修；中间增删特征时自动修复率低。
- **V2 算法 PR #31040（2026-06 开，2026-08 仍 draft review）**：可解码的 9 段式名字、去 StringHasher、含 V1→V2 迁移；集成测试仍在发现复合模型失效案例。
- 官方总结四条显式设计意图路径：datum 显式定位、草图挂主平面、**语义选择（`.faces(">Z")`，"CadQuery 是我所知唯一提供此类设施的工具"）**、建模即代码（OpenSCAD/脚本）。→ A6（几何谓词禁裸索引）+ 历史重放 + datum 节点 = 与社区结论一致的正确组合；且 MyCAD 应在重放引用失效时**显式报错指向具体命令**（学 FreeCAD 第一目的），不静默选错。

### E5（商业转换器授权，exa 官网 2026-09-17）

- **CAD Exchanger SDK**：开发费（首年入门费+年维护）**+ 分发费按终端机器按季结算**（license key 绑 host-id）；CLI 绑服务器 MAC、不可随桌面分发；系统集成商场景客户须持证。免费试用 60 天。
- **ODA**：年费会员制，**按公司一口价、无 per-developer/per-deployment 费**；Core Package（会员即含）= STEP/IGES/JT/QIF/STL/OBJ；MCAD SDK（Sustaining+ 扩展）= sldprt/ipt/CATIA/NX/Creo/Parasolid/ACIS/JT/SolidEdge/Rhino 统一 Common API，任何格式→STEP 导出；2026-04 试用仅 SolidWorks/Inventor。
- 结论：两者都**不能随 Apache-2.0 本体再分发**。插件缝设计为"外部适配器、集成商/最终用户持证自装"不变；若未来公司统一采购，ODA 商业模型对桌面产品更友好（无席位费），ADR-005 记录两条路径。

### E6（FreeCAD 文档/事务模型，exa 源码+wiki 2026-09-17）

- .FCStd = zip：`Document.xml`（对象/参数/表达式/单位）+ `GuiDocument.xml`（仅 GUI 态）+ 每对象 `*.brp`（BREP 几何快照，免全部重算）+ `*.brp2`（ElementMap 拓扑命名映射）+ thumbnails/；三层持久化 Document→DocumentObject→Property 实现 Base::Persistence（XML+二进制流）；支持 Partial Loading。
- Undo：命名 Transaction 栈（openCommit/commit/abort），全局事务 ID 可跨文档分组，GUI 可 undo 到指定 id（多步需用户确认）；recompute 按依赖图重算受影响特征。
- 对 MyCAD：v1 纯 JSON 有序命令+全量重放**已足够**（法兰级模型重放毫秒）；演进口=若大模型重放变慢，再引入"命令后 brep 快照缓存"（类比 .brp）；A5 不变但在 ADR-002 写明该演进方向与存档版本迁移钩子；不需要 V1 ElementMap（谓词引用替代）。

### E7（视口，exa 源码 2026-09-17）

- tpaviot/pythonocc-core master `backend.py` 已含 `PYSIDE6`/`PYQT6` 后端（搜索序 PyQt5→PyQt6→PySide2→PySide6→wx→tk），Linux 上 `qt6_force_xcb_on_linux()`；但 issue #1421（2025-03）显示 7.8.1 + PySide6 嵌入仍有"no backend loaded"类坑。**关键：pythonocc-core 绑定 `pythonocc-nucleus`（OCC.Core），与 build123d 的 cadquery-ocp-novtk（OCP）是两套 OCCT 原生运行时，同进程混用有符号/句柄冲突风险 → 见 R15**。
- VTK 官方 `vtkmodules/qt/QVTKRenderWindowInteractor.py` 已原生支持 PySide6/PyQt6 + QOpenGLWidget（2021/2022 合入，自动探测绑定）。
- 阶段 1 路线（ADR 锚点，不在阶段 0）：①网格预览用 OCCT tessellation→VTK/pyvistaqt 或自写 QOpenGLWidget，经 Viewport 抽象隔离；②原生 AIS 视口若上马，需统一 OCCT 绑定（要么 OCP 自封 AIS，要么整体评估切换），不能双运行时；③Linux 默认强制 XCB，Wayland 单独验证。

### E8（本地 LLM 结构化，exa 2026-08）

- Ollama v0.5+：请求 `format` 传 JSON Schema→编译 GBNF 语法→逐 token mask，结构合法"不可能生成坏 JSON"；但不做完整语义校验（中途截断/枚举值仍可能错），温度 0 + Pydantic 后置校验是标配；深嵌套/递归 schema 降质；部分 thinking 模型关 think 会静默丢约束。
- llama.cpp server 原生 tool_calls 已保证参数符合 JSON Schema（PR #9639）；实战三条铁律：agent/coder 微调模型（Qwen3-Coder/Devstral 类）、原生 tool chat template（`ollama show --modelfile` 验）、工具面要小；解析失败免费修一次、参数校验错误回灌模型、修复循环上限 2 次。
- → 阶段 2 边界（ADR 锚点）：命令注册表自动生成 tool schema；本地/云端同一 OpenAI 兼容抽象；**dry-run 校验 + 用户确认门不可省**（语法合法≠几何/意图正确，E4 已证）；阶段 0 只实现 Plan 数据结构+状态机+schema 生成的纯函数（可无模型单测）。

### E9（龙芯，exa 官方+社区 2026-09-17）

- CPython 3.12+ 已原生识别 loongarch64 triplet；但 PyPI/Warehouse **仍不接受 loongarch64 wheel 上传**（discuss.python.org #105548，2026-01 仍在走 PEP 流程）；官方 manylinux 无 loongarch64 tag；patchelf/uv/auditwheel/swig 已支持，cibuildwheel 靠社区 fork/镜像。
- 龙芯官方 PyPI 镜像按 glibc 分源：glibc 2.28→`pypi.loongnix.cn`；glibc≥2.38→`lpypi.loongnix.cn`（注意 2.28 源的 wheel 在新系统装得上但不能用）；社区 `mirrors.loong64.com`（manylinux_2_36/2_38 交叉镜像）；Loongson-Cloud-Community/pypi 每日 CI 已构建 90+ 包含 **cadquery-vtk**（但无 cadquery-ocp 条目）→ OCCT 7.9 绑定仍需自建。
- T3 go/no-go 判据（ADR-006）：有技术路径（源构建 OCCT+OCP、龙芯镜像装纯 Python/科学计算包、QEMU CI），成本=自维护原生构建；阶段 0/1 不承诺，阶段 1 末出真机/容器 spike 决议。

### E10（OCCT 免费格式 + DE_Wrapper，官方文档 2026-09-17）

- OCCT 7.8 开源 DataExchange：STEP(AP203/214/**AP242**)/XCAF(.xbf)/BREP/IGES(≤5.3)/OBJ/STL/PLY(只写)/glTF2(RW)/VRML 均开源（DE_Wrapper 表，VendorName="OCC"，STEP 线程安全须每 reader 独立 DESTEP_Parameters）；glTF 读依赖 RapidJSON+Draco(BSD/Apache 干净)；STEP/IGES 解析生成器用 flex/bisol（GPL，仅构建期工具，不污染发行授权）。
- **商业 Advanced Components：ACIS SAT、Parasolid、JT、IFC 等**（与 E5 互证）。STEP XML SDK 亦商业。
- OCCT 7.8 的 **DE_Wrapper 统一 provider 模型（FormatName×VendorName 分组、统一 Parameters、shape 或 XCAF document 两种目标）= MyCAD `FormatProvider` 注册表的直接设计样板**：免费 provider 名 "OCC"，商业 provider 名可插；import 分级（BRep 哑实体 / XCAF 带装配颜色名称材料 / 可编辑特征——任何外部格式都达不到第三级）。
- 3MF：不经 OCCT，build123d 依赖已自带 lib3mf 2.5.0（aarch64 自动切 py-lib3mf）；DXF：自带 ezdxf 1.4.4（MIT）→ 免费序列阶段路线 STEP/STL/BREP→IGES/glTF/OBJ→3MF/DXF，无新原生依赖。

### E11（技术尖刺，本机实证 2026-09-17，/tmp/opencode/mycad-spike/，非产品代码）

- `uv venv`（系统 Python 3.12.3）+ 清华镜像 `uv pip install build123d==0.11.1`：解析 46 包 44s，下载 5m54s（OCP 64.3MiB 为最大件；直连 files.pythonhosted 两次 15min 超时，国内镜像可用），安装瞬时完成。实装：cadquery-ocp-novtk 7.9.3.1.1 + proxy 7.9.3.1.1、numpy 2.5.3、scipy 1.18.1、scikit-learn 1.9.1、ezdxf 1.4.4、lib3mf 2.5.0 等；`import build123d, OCP` 成功。
- 法兰脚本 `flange_spike.py`（Cylinder φ80×8 → SUBTRACT 中心孔 φ20 → PolarLocations(r25,4) 减 4×φ6）：
  - 体积脚本打印 **36794.3332 mm³**（4 位小数舍入显示）；解析真值 π·8·(40²−10²−4·3²)=**36794.333158843656…**（打印值与真值差 4.12e-5，非"精确相等"；Momus 第一轮评审 #1 指出，golden 已改正为全精度/math 公式直算，容差 1e-6）；
  - 1 个 solid、圆柱面 6（外圆+5 孔）、包围盒 80×80×8 断言通过；
  - `export_step` 24,390 B、`export_stl` 152,084 B；`import_step` 往返后 1 solid 且体积一致。
- 结论：C1+C2+C8（STEP/STL）技术风险关闭；geom 层命令式原语（原型体/布尔/极阵列/查询/导出）在 build123d 0.11.1 上全部直接可得。
- 运维注记：国内网络环境安装文档需写镜像配置（UV_INDEX/--index-url 清华或阿里），CI 用官方源（GitHub Actions 海外）。

## 6. 风险登记

- R1 ~~OCP conda 包对 Py3.12 滞后~~（已被 E1 消解：pip wheel 覆盖 cp310-314）→ 新风险 R13 见下。
- R2 build123d API 在 0.x 迭代有 breaking → environment 精确 pin + geom 层收口。
- R3 选择器重放脆弱（TNP）→ A6 谓词纪律 + golden 回归。
- R4 阶段膨胀（想在阶段 0 加 UI/Agent）→ Scope 明确 Out 列表。
- R5 无 git → 先初始化再动手。
- R6 OCCT 视口嵌入（阶段 1）可能延期 → 网格预览占位，Viewport 接口在阶段 0 以"几何查询/tessellation 数据"形态预留。
- R7 商业 CAD 内核格式（x_t/sat/sldprt/NX/CATIA/JT）无开源读路径 → C8 只做接口+商业插件生态位，路线图不承诺免费支持，需求沟通时明确预期。
- R8 LoongArch/信创依赖生态（conda 无 loongarch64、OCCT 移植、Qt6 缺位）→ T3 出 go/no-go 证据简报；最坏降级为"战略路线"不进阶段承诺。
- R9 插件信任与安全：任意 Python 插件=全信任 → manifest 权限声明+文档告知，v1 不做沙箱化插件（沙箱仅约束 Agent 生成代码）。
- R10 MCP 远程确认 UX：外部客户端触发改模时确认 UI 如何呈现 → 阶段 2 设计；阶段 0 ADR 只锁定"任何传输面不得绕过确认门"。
- R11 DWG 等闭格式的合规雷区 → 不碰逆向库；ezdxf 只碰 DXF；ODA 转换器由用户自装。
- R12 范围蔓延：三个补充点若全要求阶段 0 实现，MVP 会失焦 → 原则=**阶段 0 定缝+ADR+可验证的最小实现**（仅注册表缝/元数据/查询接口），生态与适配工程按路线图推进。
- R13（E2 精确化）OCP pip wheel 要求 **manylinux_2_31（glibc≥2.31）**：**统信 UOS V20 桌面版（D 版，Debian10，glibc 2.28）确定不可直装**；麒麟 V10 SP1/SP3（glibc 2.31+麒麟补丁）可直装但须实机/容器回归。缓解：ADR-006 声明支持基线 glibc≥2.31，旧版走源构建/容器/升级 V11 建议，列为已知限制不阻塞 T1。
- R14 build123d 0.x 每数个 minor 有 API breaking（0.9→0.11 依赖从 ocp 切到 cadquery-ocp-novtk 即为一例）→ pyproject 精确 pin `build123d==0.11.1`（权威写法；历史上出现过的 `==0.11.1.*` 是错误通配，执行者不得采用）并把全部 OCCT 触碰封进 geom 层；升级=独立 spike + golden 重放。
- R15（E7 新增）**双 OCCT 运行时冲突**：pythonocc-core(pythonocc-nucleus, OCC.Core) 与 cadquery-ocp-novtk(OCP) 不宜同进程。阶段 0 headless 不受影响（只装 OCP 系）；阶段 1 原生 AIS 视口必须先做绑定统一决策（OCP 自封 AIS vs 整体换栈），网格预览（VTK，纯网格不碰 OCCT 运行时）是无冲突过渡。ADR-007（阶段 1 预备）占位记录。
- R16（E3 新增）MCP SDK v1→v2 大改（类名/依赖/线程模型），阶段 0 不实现则无负担，但 ADR-004 须写"落地时锁主版本、工具面经 Bus 计划面、确认经显式 token"三条不变量，使实现与 SDK 版本解耦。
- R17（E6）全量历史重放在大模型下有性能上界 → 接受（法兰级毫秒）；ADR-002 预留"brep 快照缓存"演进而 v1 不做，避免过度工程。
- R18（E11）国内网络下 files.pythonhosted 大 wheel 直连会超时（两次 15min 实测）→ 安装文档/脚本内置镜像（清华/阿里），CI 在海外用官方源；用户环境若离线走 wheelhouse/conda 备选文档。

## 7. 下一步（门控）

1. ~~收集 L1–L8 + 抽查验证~~ **已完成**：librarian 通道在本环境普遍 30min 零产出挂死（9/9），改由规划师直查一手源完成 E1–E10，并以本机安装+法兰尖刺(E11)实证核心链路。
2. 回填 §4/§5/§6/§8 → **形成审批简报（下一条消息）**：采用默认 + 阶段 0 范围 + 三个补充点如何落缝 + 阶段 1–3 路线图。
3. **status: awaiting-approval** → 等用户明确批准 → 运行 scaffold-plan.mjs(--unclear) + APPEND todos（Implementation+Test=1 todo，含 References/Acceptance/happy+failure QA 证据路径/Commit）→ TL;DR 最后写 → Metis gap 分析 → 双 Momus 高精度评审（UNCLEAR 自动：原生 momus + 独立 Codex CLI 隔离工作区），两者 APPROVE 后交付简报等 start；禁止自行实现。

## 8. 阶段 0 范围草案（待证据收敛后定稿）

**In（最小可验证）**：
- 环境骨架（**uv + pip**；Python 3.12；精确 pin build123d==0.11.1 / cadquery-ocp-novtk 7.9.3.1.1；Win+Linux CI 矩阵 via setup-uv）、git、pyproject src 布局、ruff/类型检查/pytest；**安装文档含国内镜像配置（R18）**；附 conda/离线 wheelhouse 备选安装文档（企业网）
- geom：build123d 收口（**E11 尖刺已证 API 直接可得**：BuildPart/Cylinder/Mode.SUBTRACT/PolarLocations/filter_by(GeomType)/export_step/import_step/export_stl）；原型体/布尔/拉伸/旋转/孔/环形阵列/圆角；STEP/STL I/O；质量属性查询；可调精度 tessellation 数据接口
- commands：JSON Schema 注册表（entry-point 声明约定）+ CLI 文本映射 + 校验器
- core：Document（有序历史+metadata: part_no/revision/material/source）、Bus（undo=重放、批事务快照回滚）、headless 信号总线（不依赖 Qt）
- NamedGroup（命名选择组，CAE 缝）、FormatProvider 注册表（C8 缝）、插件 manifest/API 版本约定（C7 缝）
- CLI：REPL+脚本，英文 ASCII 语法；法兰脚本端到端
- 存档 JSON v1（version + 迁移钩子）
- ADR-001…006；6 个 ADR
- golden 法兰几何断言 + 往返测试 + examples/ 法兰计划
- NOTICE/SPDX 头

**Out（仅 ADR/路线图，阶段 0 不实现）**：Qt/UI、真实 LLM 调用、MCP server 代码、PLM 检入检出、mesher、商业格式适配器、信创装机认证、打包发行物。
