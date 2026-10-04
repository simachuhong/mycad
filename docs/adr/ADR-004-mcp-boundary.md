# ADR-004 MCP 边界（只决策不实现）

Status: Accepted 2026-09-17

## Context

MyCAD 的智能体助手需要一条标准互操作通道，使外部 AI 客户端也能驱动建模。Model Context Protocol（MCP）是 Agent 互操作趋势；2026-07-28 规范明文要求敏感操作人工确认，且规范无协议级会话——跨调用状态必须由创建工具返回显式句柄、后续调用携带（E3）。同时确认流是产品红线（需求分析书 §6：默认必须确认；"信任模式"若未来提供不得默认开启），任何传输面不得绕过确认门（R10）。阶段 0 是 headless MVP：本 ADR 只锁决策与边界，不实现、不引入 mcp 依赖（面向 Agent 的工具 schema 形态只存在于本 ADR 与计划附录 A 的文字规范中，工具 schema 生成代码是阶段 2 产品）。

## Decision

1. **形态**：MyCAD 作为 stdio MCP server（本地优先，与 NF-02 一致；Streamable HTTP 为后续可选 transport，不改变工具面契约）。
2. **工具面 = 只读查询 + 计划面**：`list_commands` / `make_plan` / `validate_plan` / `query_document` / `export_dry_run`。外部 AI 与内部 Chat 同源（技术路线 §2 原则 2 多入口同源）：工具面只产出与校验 Plan、不直接改模型；执行必须走确认门后经 Command Bus 提交（ADR-001）。
3. **状态用显式 plan_id 句柄**：MCP 规范无协议级会话（E3），`make_plan` 返回显式 `plan_id`，后续调用携带该句柄定位计划。
4. **确认令牌红线**：`confirm_execute(plan_id, confirmation_token)`——token 只能由产品侧用户交互产生，任何远程客户端（含 LLM）不可自造。这是把"默认必须确认"的产品规则映射到协议层：没有用户交互产生的令牌，confirm_execute 一律拒绝。
5. **SDK 版本策略**：落地时在 MCP Python SDK 锁主版本——v2 对齐 2026-07-28 规范（`MCPServer`），旧代码 pin <2（R16：v1→v2 类名/依赖/线程模型大改）。三条不变量使实现与 SDK 版本解耦：落地时锁主版本、工具面经 Bus 计划面、确认经显式 token。
6. **确认交互优先走规范 elicitation**：优先用规范原生 elicitation（`InputRequiredResult`，工具执行中暂停向用户索要输入的多轮往返）承载确认交互；elicitation 不可用时回退到产品侧确认 UI 产生 token。
7. **阶段 0 零依赖**：阶段 0 不引入 mcp 依赖、无任何 MCP 实现代码；本 ADR 是该边界的唯一落点。
8. **A19（国产 LLM 路径）显式处置**：阶段 2 的 LLM 选型限定在 OpenAI 兼容抽象之后——云端候选 DeepSeek/通义，本地候选 Ollama（aarch64 可行，与信创平台 T2/T3 协同）；不绑定境外 API。该选型是 accepted/future 假设：阶段 0 无任何 LLM/网络/API 调用代码（NF-02 本地优先），仅交付 Plan 纯数据结构、六态状态机与 MCP/确认边界（本 ADR）。

## Consequences

- 正面：确认红线在协议层有不可绕过的落点（token 只能来自用户交互）；plan_id 句柄使无会话协议上的状态管理明确；工具面"只读+计划面"使外部 AI 与内部 Chat 共享同一套安全模型。
- 负面/边界：远程确认的 UX（外部客户端触发改模时确认如何呈现）留待阶段 2 设计（R10）；elicitation 依赖客户端支持，回退路径必须同时维护；SDK v2 仍在演进，落地前需复核规范与 SDK 的对应关系。
- 阶段 0 交付边界重申：无 mcp 依赖、无 LLM 调用、无网络调用代码；工具 schema 生成代码属阶段 2 产品，阶段 0 不写。

## References

- docs/需求分析书.md §6（智能体确认流产品规则）、NF-02（本地优先）、NF-07（Agent 生成代码受控执行）
- docs/技术路线.md §7（禁止默认让 LLM 在无沙箱下执行任意 Python）
- 研究台账 A14（MCP 定位与 E3 修订：plan_id 句柄、confirmation_token）、A19（国产 LLM 路径）、E3（2026-07-28 规范与 Python SDK v2）、R10（远程确认 UX）、R16（SDK 版本锁定三不变量）
- .omo/plans/phase0-mvp.md T4（本 ADR 指令）、附录 A（面向 Agent 的工具 schema 规范描述）、显式延期需求登记（F-AGT-01、A19 行）
- ADR-001（确认流的 headless 投影与 confirmed_by 审计字段）
