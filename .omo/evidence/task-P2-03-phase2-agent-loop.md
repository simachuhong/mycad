# P2-03 — 失败路径状态恢复契约

日期：2026-10-23；分支 `codex/phase2-foundation`。

## 恢复规则

| 操作 | 首次失败 | 恢复成功 | 恢复再次失败 |
|---|---|---|---|
| 单命令 | handler 启动前不改几何；handler 启动后还原快照 | 恢复命令历史、metadata、named groups、dirty 与 redo，再从已提交历史重建几何 | Bus 标记 `is_healthy=False` 并拒绝后续 execute/undo/redo/edit/batch |
| 批执行 | 还原操作前完整文档与 redo 快照；Plan 标记 failed | 重放原历史；未提交的 `post_command` 等事件丢弃，只发送一次恢复后的 `geometry_rebuilt` | `ReplayDuringRollbackError` 同时保留批失败（含失败 ordinal）与实际恢复异常 |
| edit | 修订通知暂存，失败时还原命令/审计、metadata、named groups、dirty 与 redo | 重放旧历史；不发送 `command_amended`，发送已恢复几何通知 | Bus 标记不健康，异常保留原重放失败与恢复异常 |
| undo/redo | 先保存命令与 redo 状态，重建失败时恢复两者 | 重放失败前历史并通知恢复成功；重新抛出首次重建错误 | Bus 标记不健康并阻止后续写操作 |

`pre_command` 明确表示开始尝试，因此即时送达；`post_command`、`command_amended` 和重建通知在对应状态提交后送达。元数据/命名组事件也加入事务队列，失败回滚会丢弃。Document 快照覆盖命令历史、metadata、named groups 与 dirty；几何仍通过 reset + replay 恢复，不添加持久化 BREP 检查点。

插件 handler 会在打开、undo、redo、编辑和恢复时重放，契约要求确定、可重放，变更须经 `ctx.kernel.apply` 表达。文件写入、网络请求和通知等外部副作用无法由几何重放撤销；ADR-003 与 CommandHandler 文档现在明确说明这不属于 Bus 的回滚保证。

## 验证

- `uv run pytest tests/core tests/plugins -q`：270 passed（53.52 秒）。
- 最后一次信号隔离与总线状态验证：`uv run pytest tests/core/test_signals.py tests/core/test_bus.py -q`，40 passed。
- 改动路径 Ruff lint、format 与 basedpyright 均通过；basedpyright 为 0 errors / 0 warnings / 0 notes；`git diff --check` 通过。
- 失败注入覆盖单命令部分副作用、批中途失败、edit 重放失败、undo/redo 重建失败及恢复二次失败；测试断言历史、几何、redo、metadata、named groups、dirty、通知与健康门控。

## 范围与限制

本项审查邻近失败路径，不断言每种插件违规都可检测。已提交 history 的 handler 若违反重放安全契约并执行外部副作用，Bus 无法撤销该副作用；当前实现明确将其排除在回滚保证外。未运行全仓测试或 GUI/GPU 集成验收。
