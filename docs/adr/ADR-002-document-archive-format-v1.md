# ADR-002 存档格式 v1

Status: Accepted 2026-09-17

## Context

阶段 0 需要一种可审计、可 diff、Agent 友好的文档持久化格式。候选有三：内嵌 BREP 的二进制容器（FreeCAD .FCStd 路线）、纯命令历史的 JSON、混合快照。.FCStd 是 zip 容器：`Document.xml` 存对象参数与表达式、每对象 `*.brp` 存 BREP 几何快照免全部重算、`*.brp2` 存 ElementMap 拓扑命名映射（E6）。MyCAD 的 undo 语义已定为历史重放（ADR-001），几何可由历史完全重建，因此 v1 选择最轻量的纯 JSON 有序命令历史，快照缓存列为演进口而非起点。存档同时是审计载体（NF-03：计划与已执行命令可追溯）：谁在何时确认、何时改参、为什么改，必须可追溯。

## Decision

1. **格式与扩展名**：存档为 UTF-8 编码的 JSON 文件，扩展名 `.mc.json`。
2. **顶层 schema**：`{"format":"mycad.document","version":1,"metadata":{...},"commands":[{...}],"named_groups":[{"name","faces":[...],"edges":[...]}]}`。`metadata` 承载 part_no/revision/material/source 等文档元数据。
3. **named_groups 元素契约**：每个元素恰好三个键——`name`、`faces`、`edges`；`faces`/`edges` 的值为附录 A.0 谓词描述子 JSON（FaceSelector / EdgeSelector 对象数组）。CAE NamedGroup 是文档注释态：它为下游仿真/文档用途命名几何选择，**不进重放序列**，重放结果不依赖它。
4. **命令元素审计六字段**：`id` / `version` / `params` / `ordinal` / `timestamp_utc` / `confirmed_by`。`ordinal` 为 int、从 0 起；`timestamp_utc` 为 ISO8601 UTC 字符串；`confirmed_by` 可空（值可为 null）。
5. **可选数组 `amendments`（修订留痕）**：命令元素初始不含 `amendments` 键；每次经历史参数编辑 API 重放（T6）追加一条 `{"at":"<ISO8601 UTC>","actor":"<str>","from_params":{...},"reason":"<str>"}`——原 `params` 被替换为新值，但修订过程以 amendments 留痕，审计链完整。
6. **打开与审计字段恢复**：`open` 时恢复全部审计字段；打开后的重放与参数编辑重放都**不改写原 timestamp**——原 `timestamp_utc` 是该命令首次入史的事实，任何后续操作只追加 amendments、不篡改历史时间戳。
7. **版本校验与迁移钩子**：读取时校验 `format` 与 `version`；版本迁移经 `migrations.py` 钩子注册表进行，v1 无迁移体（注册表为空，钩子机制先行）。
8. **阶段 0 无任何导入型历史节点**：STEP 读仅是测试辅助路径（`tests/helpers/`，用于导出件往返断言），不进存档 schema；存档中的每条命令都是可重放的建模命令，无导入型节点字段。
9. **brep 快照缓存**：列为未来 v2 演进口（E6 FreeCAD .FCStd 对照：若大模型全量重放变慢，v2 引入命令后 brep 快照缓存，经 version 迁移钩子升级存档），v1 不做。

## Consequences

- 正面：纯 JSON 可 diff、可审计、Agent 可读写；审计六字段 + amendments 使"何时、何人、改了什么参数、为什么改"全程留痕；迁移钩子先行使 v2 演进无需破坏性变更。
- 负面：全量重放成本随历史长度线性增长（R17，接受为已知限制，演进口见第 9 条）；`document.import_step`（导入 STEP 作为历史节点）是阶段 1 演进口——F-DOC-03 的产品化 STEP 导入属基线自身的阶段 1 分期，届时再定义导入型节点形态，本 ADR 不为它预留任何字段。
- 每条命令的 `version` 字段是协议增强（支撑未来同 id 多版本共存），与 CommandSpec 的 `undo_compensation` 字段一样属"增强不冲突"，明确不是基线偏离、不计入偏离计数。

## References

- docs/需求分析书.md NF-03（可审计：计划与已执行命令可在 Chat/CLI/日志中追溯）
- 研究台账 A5（存档=JSON 元数据+有序命令、brep 不内嵌；#round10-NB6 计划覆盖更新：阶段 0 无导入型历史节点）、E6（.FCStd 结构对照与重放性能结论）、R17（重放上界与快照缓存演进口）
- .omo/plans/phase0-mvp.md 附录 A.0（谓词描述子 JSON）、T4（本 ADR 指令）、T6（历史参数编辑重放与 amendments 追加规则）
- ADR-001（undo=历史重放、坐标单位约定）、ADR-005（STEP 读写的产品化分级与阶段 1 读路径）
