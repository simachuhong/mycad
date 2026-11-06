# U11 Failed Prefix Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让下游绑定引用失效时，在严格隔离的成功前缀上选择替代面，并以完整候选原子预览和提交修复。

**Architecture:** 为失败结果新增单独的前缀交互场景，绝不把它作为成功场景；保持现有失败候选无法授权。前缀拾取只允许当前候选、修订、会话和 generation 的几何，重新 stage 同时包含上游修改和显式选择的下游修复，只有完整重放成功才能确认。GUI 应展示失败命令、参数路径及受影响下游；不支持或歧义的面不猜测。

**Tech Stack:** Python、PySide6、隔离候选、Command Bus、OCCT、pytest。

**Spec:** `docs/design/2026-11-04-unified-ui-todo.md` U11；`docs/superpowers/specs/2026-11-02-isolated-replay-candidates-design.md`；`docs/superpowers/specs/2026-11-03-m2a-datum-interaction-design.md` A14。

## Global Constraints

- 失败前缀不授权提交；源模型、redo、格式和审计在预览/取消时不变。
- 前缀必须是失败命令之前重放成功的隔离几何；禁止拾取失败命令的局部副作用、未执行的下游和源场景。
- 场景及拾取只对同一文档、修订、会话、候选和 generation 有效。
- 替代面由用户明确选择且必须具备唯一设计身份；仅支持盒体平面和圆柱端面。
- 所有命令修改由单个候选一次性经 Bus 提交；不得承诺复合修改的单步 undo。

## Review Focus

- 失败命令部分写入：展示的前缀不含局部副作用，无法确认。
- 来源或候选更改、会话切换：旧失败场景和拾取全部拒绝。
- 无可用前缀、非绑定孔错误、曲面或歧义面：清楚提示，禁止猜测。
- 修复继续失败、用户取消：原文档及输入不变，可再次编辑。
- 成功修复后审计、保存重开与更新：候选摘要和全部被编辑命令正确保留。

### Task 1: 失败前缀隔离拾取

**Files:** `src/mycad/app.py`, `tests/app/test_replay_candidates.py`, `tests/geom/test_replay_candidates.py`。

- [x] 新增独立 `failure_scene` 和仅对当前失败前缀有效的场景检查与绑定拾取接口；不改变成功 `scene` 语义。
- [x] 验证失败前缀可拾到前缀中的唯一设计面，源拾取、其他候选、旧 generation 均被拒绝。
- [x] 对抗注入失败命令局部副作用，证明拾取几何来自独立前缀重放且失败候选无法授权；运行 scoped 测试与类型检查。

### Task 2: 历史候选界面中的有限修复

**Files:** `src/mycad/ui/right_panel.py`, `src/mycad/ui/main_window.py`, 适当拆分独立交互组件，`tests/ui/test_history_edit.py`。

- [x] 向用户显示具体失败命令和路径，允许针对 `feature.hole@3` 的 `target_face` 显式进入失败前缀选面；其他错误只说明。
- [x] 同时保留原上游输入、失败命令参数与原审计原因；用选面替换下游绑定，重新形成完整修改集并隔离重放。
- [x] 完整候选成功后明确展示全部影响与修复来源，确认才原子提交；取消、切会话、再次失败都保留源模型。
- [x] 用真实窗口和鼠标测试上游改变→失效→显式选面→完整预览→确认→保存重开，并测试失败、取消和过期。
