# E3-A 隔离候选重放与原子确认验收

日期：2026-11-02。范围：后端候选会话、源 Bus 一次性授权/原子提交和真实几何验收；不包含 GUI。

## 验收结果

最终定向集成命令：

```bash
uv run pytest tests/core/test_replay_proposal.py tests/core/test_command_identity.py tests/core/test_bus.py tests/core/test_bound_refs.py tests/core/test_persistence.py tests/app/test_replay_candidates.py tests/app/test_open_atomic.py tests/geom/test_replay_candidates.py tests/geom/test_bound_face_holes.py tests/geom/test_command_identity.py tests/geom/test_topology_evolution.py tests/test_layering.py -q
```

结果：`197 passed in 22.91s`。

静态检查命令及结果：

```bash
uv run ruff check src/mycad/core/bus.py src/mycad/app.py tests/core/test_replay_proposal.py tests/app/test_replay_candidates.py tests/geom/test_replay_candidates.py
# All checks passed!

uv run ruff format --check src/mycad/core/bus.py src/mycad/app.py tests/core/test_replay_proposal.py tests/app/test_replay_candidates.py tests/geom/test_replay_candidates.py
# 5 files already formatted

uv run basedpyright src/mycad/core/bus.py src/mycad/app.py tests/core/test_replay_proposal.py tests/app/test_replay_candidates.py tests/geom/test_replay_candidates.py
# 0 errors, 0 warnings, 0 notes
```

先写授权、提交与回滚测试，再运行原定红测命令：

```bash
uv run pytest tests/core/test_replay_proposal.py tests/app/test_replay_candidates.py -q
```

实现前结果为 `6 failed, 25 passed`；失败均因 `authorize_replay_candidate`、`commit_replay_candidate`、`ReplayCandidateSession.authorize_commit` 尚未实现。实现后这些新增场景转绿。

## 场景覆盖

| 验收场景 | 证据 |
|---|---|
| v4 带 redo 预览升级后取消；重复预览复用身份 | `test_candidate_preview_reuses_staged_identity_and_cancel_preserves_v4_redo` |
| v4 升级并追加绑定孔，确认后原子提交实际几何 | `test_v4_upgrade_and_bound_hole_candidate_has_expected_geometry` |
| 上游实体替换和下游绑定孔改绑完整预演、一次提交 | `test_candidate_commits_upstream_and_downstream_bound_hole_repair` |
| 重放在第 0、1、2 条命令失败时返回准确首错与成功前缀 | `test_replay_candidate_failure_stops_at_each_history_position` |
| session/source 过期、提案字段与摘要篡改、身份升级签名篡改、跨 Bus 凭据 | `tests/app/test_replay_candidates.py` 与 `tests/core/test_replay_proposal.py` 中的对应用例 |
| 成功结果过期、重复消费、提交重建失败回滚历史/审计/格式/dirty/redo/几何/revision/事件 | `test_candidate_commit_requires_latest_success_and_current_session`、`test_replay_candidate_grant_rejects_tampering_and_is_consumed_once`、`test_replay_candidate_commit_failure_restores_source_and_discards_events` |
| 空/空白异常消息仍返回结构化失败；插件前的前缀重放失败时报告真实首错并重建更短的成功几何；v4→v5 升级提交失败完整恢复活动/redo 身份 | `test_replay_for_candidate_normalizes_empty_exception_reason`、`test_empty_exception_message_returns_failed_preview_and_preserves_source`、`test_unsupported_command_failure_uses_actual_replayed_prefix_failure`、`test_unsupported_command_failure_rebuilds_prefix_before_mutating_failure`、`test_failed_identity_upgrade_commit_restores_v4_active_and_redo_history` |
| 插件命令历史在候选执行前拒绝 | `test_candidate_rejects_plugin_history_before_running_its_handler` |

提交成功时改参命令保留原 audit 字段并各追加一条 amendment；内容编辑只递增一次 revision、清空 redo 并在重建后发布事件。身份升级单独提交时保留并升级 redo 身份。提交重建失败消费该凭据，恢复源状态，并仅发布恢复用的 `geometry_rebuilt` 通知。

独立只读审查首先发现空异常消息会破坏结构化失败，之后指出前缀诊断和失败 scratch 几何的边界；均已补 RED/GREEN 回归测试并修复。失败前缀现在逐步缩短，并在新内核中重建成功几何。审查还建议覆盖 v4→v5 与内容编辑合并提交失败后的完整回滚；该测试验证格式、活动/redo 命令身份、审计、revision、dirty 和几何均恢复。最终复核未发现剩余可操作问题。

## 边界

- 交付的是隔离候选 API；本切片不接入桌面 GUI。
- 原子提交保证整体成功或失败，但不新增“一步撤销整次多命令修复”的语义；amendment 仍沿用当前 undo 契约。
- 不实现 split/merged 后继面的持久选择契约或任意失效拓扑重选；unsupported plugin history 继续显式拒绝。
- E3-B、E3-C、E3-D、E3 整体以及 P2-12/P2-19 仍未完成。
