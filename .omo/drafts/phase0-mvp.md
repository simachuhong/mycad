---
slug: phase0-mvp
status: reviewed-ready
intent: unclear
pending-action: 计划已通过全部评审（Codex Momus 第 12 轮增量二审 APPROVE，13/13 delta checks+12/12 不变量全 PASS）。已交付中文简报，锁等用户显式 start 指令；收到 start 后按 .omo/plans/phase0-mvp.md 的 9 波 W0-W8 从 T1 开始执行
approach: 阶段0 headless 可编程 MVP：命令 schema→校验→Bus(重放 undo/批事务快照)→Document(有序历史)→geom(build123d 0.11.1/OCP 封层)→STEP/STL；CLI REPL+脚本；JSON 存档 v1；扩展缝(entry_points/FormatProvider/信号/元数据/NamedGroup)+ADR-001..006；阶段1-3 仅路线图锚点。三点补充(插件/MCP/PLM/CAE、格式转换、跨平台+信创)落为 C7/C8/C9 接缝组件。
---

# Draft: phase0-mvp

> 完整研究台账（E1–E11 证据、A1–A20 假设、R1–R18 风险、范围草案）见
> **`.omo/drafts/phase0-mvp-research-ledger.md`**（218 行，规划师手写、scaffold 前改名保留）。
> 本文件是 ulw-plan 脚手架恢复点，只记录当前相位状态。

## Components (topology ledger)

| id | outcome | status | evidence |
|----|---------|--------|----------|
| C1 环境/打包 | uv+pip 精确 pin、src 布局、三平台 CI（ubuntu-22.04/24.04/windows-latest） | active | ledger §3, E1/E11 |
| C2 geom 适配层 | 8 个 P0 原语+谓词查询+STEP/STL，不泄漏 OCP | active | E11 尖刺 |
| C3 命令模型/注册表 | 稳定 id+JSON Schema+校验+CLI 映射，三入口同源 | active | docs/技术路线.md |
| C4 Document/Bus | 有序历史真相源、重放 undo、批事务快照回滚、JSON v1 | active | E6 |
| C5 CLI | REPL+脚本，文本⇄JSON 等价，法兰端到端 | active | docs/需求分析书.md §8 |
| C6 质量/验收 | golden 法兰断言、往返测试、Apache 合规 | active | E11 体积解析真值 36794.3331588437（尖刺打印 36794.3332 为舍入值） |
| C7 扩展缝 | entry_points+manifest 版本化、信号、MCP/PLM/CAE 仅缝+ADR | active | E3/E8 |
| C8 FormatProvider | provider 注册表(对齐 OCCT DE_Wrapper)、import 三级、格式矩阵 | active | E5/E10 |
| C9 跨平台/信创 | T1 Ubuntu 双版本+Win x64 CI 三 job；T2 aarch64 glibc≥2.31；T3 龙芯 go/no-go | active | E2/E9 |

## Open assumptions (announced defaults)
见 ledger §4 A1–A20。最高杠杆默认（Metis contrarian grill 目标）：
1. 阶段 0 边界=仅 headless（UI/LLM/MCP 实现全后置）。
2. undo=删命令+全量重放（不做 per-command inverse、不做 brep 快照缓存）。
3. build123d 0.11.1 精确 pin、全部 OCCT 封进 geom 层。

## Findings (cited - path:lines)
- E1–E11 全部在 ledger §5（含来源与实测数据）。
- 尖刺代码在 /tmp/opencode/mycad-spike/（临时区，非仓库资产，法兰参数将移植为 examples/ + golden）。

## Decisions (with rationale)
- pip+uv 主路径（PyPI README 明示；conda-forge 滞后 0.9.1）。
- 命令参数禁裸索引、强制几何谓词；重放失效显式报错（FreeCAD 官方四路径背书）。
- MCP server 工具面=只读+计划面；confirm_execute 须用户交互 token；阶段 0 仅 ADR-004。
- 商业格式（JT/x_t/sat/sldprt/NX/CATIA）=外部持证插件，不进 Apache 核心；DWG 不碰。
- 平台基线 glibc≥2.31；UOS V20 桌面(2.28) 已知不支持；龙芯阶段 1 末 spike。

## Scope IN
见 ledger §8 In（环境骨架/geom/commands/core/CLI/存档/三缝/6 ADR/golden/NOTICE）。

## Scope OUT (Must NOT have)
Qt/PySide6/UI、真实 LLM 调用、mcp 依赖与 server 代码、PLM 检入检出、mesher/CAE 求解、商业格式适配器、信创装机认证、安装包发行物、CadQuery/pythonocc 进依赖。

## Open questions
无（UNCLEAR 路径：全部以带证据默认收敛，用户在审批/TL;DR 行使否决）。

## Approval gate / review log
- 审批简报 m0060 已提交；系统 TODO 续跑指令要求无许可推进；规划师判断生成计划工件=用户"做规划"的直接交付物，交付后仍锁等显式 start，不构成实现。
- 子代理基础设施本环境全挂（9/9 librarian、Metis bg_bde1e036 4 次尝试、原生 momus 均零产出/超时）→ Metis 缺口分析由规划师本人执行（证据 `.omo/evidence/metis-gap-phase0-mvp.md`，16 项全回填）；高精度评审改用独立 Codex CLI 隔离评审岛（.omo/review/，火山方舟 deepseek-v4-pro，wire_api=responses）。
- Codex Momus 第 1 轮：REQUEST-CHANGES 16 blocker+6 NB → 全部回填（golden 真值修正/附录 A 字段级 schema/异常闭合清单/波次/STEP 读降测试路径/存档六字段/BatchRollbackError 单语义/删 schema 代码/priority/ADR 脚本验收等）。
- Codex Momus 第 2 轮：REQUEST-CHANGES 13 blocker+6 NB → 全部回填（三 CI job 统一/schema 子集 13 关键字/$ref/Plan 恰好 6 边/mode=cut 归 T2/退出码 0-1-2/第 15 类 ProviderConflictError/CommandHandler 契约+CommandContribution/T8→T7 解环 9 波/偏离恰好 2 处/edit_and_replay+amendments/DTO 唯一/fillet 实测签名 Part.fillet(radius, edge_list)/undo_compensation 字段/golden Group B 68455.3039217216/_formula 键/GeometryExporter 协议/NOTICE 全闭包核对/revolve 轴 1e-9/ADR 精确短语白名单）。
- 第 3-11 轮：REQUEST-CHANGES 逐轮回填，blocker 收敛轨迹 **16→13→7→6→10→8→7→6→9→2→6**（含 T8 反向引用 AppServices 解环、验收产物 .gitignore+rm 双保险、键序 owner=T3、插件夹具 monkeypatch、封层白名单补 step_roundtrip、51200 体积修正、defs 唯一注入点=CommandRegistry(schema_defs)、Hole 共享 def+根级 $ref、Plan(steps,status="draft")、to_cli 全键含 default 填充+整数 float 无小数点、tests/typing 改名+--ignore 双保险等）。
- 第 12 轮：两次全量评审死于 429 限流（~54 万 tokens 浪费）→ 用户决策转**增量评审**（只审第 11 轮 13 处回填+不变量抽查）；增量一轮 3 残留（T5 base_hole 内联表述/T9 安装路径二源/type-ignore 白名单旧表述）→ 回填后**增量二轮 APPROVE**（13/13 delta checks PASS、无新矛盾、12/12 不变量 PASS；裁决 `.omo/review/momus-codex-12d2.md:2712`；岛终态 commit `14bfb0c`）。
- 计划终态：11 todo / 9 波（W0–W8）/719 行；权威文件 `.omo/plans/phase0-mvp.md`。
- APPROVE 后：已交付中文简报（方法+默认+三补充落位+评审结论），等用户显式 start；禁止自行实现产品代码。
