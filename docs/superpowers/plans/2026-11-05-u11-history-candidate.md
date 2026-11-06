# U11 History Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将现有历史改参入口接入隔离重放候选，成功预览后才能确认提交，失败和取消不改变源模型。

**Architecture:** 沿用 `HistoryEditDialog` 的类型化参数、差异及下游说明；主窗口通过既有串行执行单元创建并预览 `ReplayCandidateSession`，将结果交还当前对话框。确认仅提交同一文档、同一修订、同一参数和原因的成功候选；关闭、修改、会话切换及失败均失效。此包先保证真实候选流程，再将入口收敛到统一命令条；绑定孔和有限重选另行实现。

**Tech Stack:** Python、PySide6、既有 Command Bus 和 ReplayCandidateSession、pytest-qt。

**Spec:** `docs/design/2026-11-04-unified-ui-todo.md` U11。

## Global Constraints

- 模型仅通过 Command Bus 修改；候选预览不更改源文档或内核。
- 所有 Qt 更新在 UI 线程；重放和提交由文档串行执行单元执行。
- 旧格式升级与有身份的绑定操作不得隐式确认；不改变已有审计与持久化协议。
- 不重置用户工作区或提交现有混合修改。

## Review Focus

- 下游重放失败：显示失败命令，确认不可用，原模型和草稿保留。
- 参数或原因在预览后变化：旧候选不可提交，要求重新预览。
- 预览执行中关闭对话框或切换文档：迟到结果不可修改 UI 或提交源文档。
- 源文档修订变更：候选授权明确拒绝，原文档不被覆盖。
- 成功提交及取消：审计、撤销、保存重开与模型状态保持一致。

### Task 1: 隔离候选预览与明确提交

**Files:** `src/mycad/ui/right_panel.py`, `src/mycad/ui/main_window.py`, `tests/ui/test_history_edit.py`。

- [x] 新增真实窗口测试：成功候选预览时源历史不变，点击确认后仅提交该候选；失败显示下游命令并禁用确认。
- [x] 测试预览后修改参数或原因、取消、文档切换和源修订变化均不能提交旧候选。
- [x] 对话框发出预览请求，主窗口以执行单元为当前文档创建并预览 `ReplayChangeSet`；对话框只展示与自身仍匹配的结果。
- [x] 确认通过同一候选的授权与提交接口，关闭或失效时释放候选；维护现有审计原因和结果反馈。
- [x] 运行 `tests/ui/test_history_edit.py`、相关会话与候选测试以及修改路径 lint、format、basedpyright。

### Task 2: 命令条承载与剩余 U11

- [x] 在隔离候选流程稳定后，将影响、失败、接受和取消状态迁入统一命令条；由“参数…”打开原类型化编辑器，关闭编辑器保留草稿，字段或原因变化使旧候选失效。
- [x] 历史命令条活动期间阻止文档切换、保存、导出及撤销；工作线程运行时取消延后清理，失效修复接手同一失败候选。
- [ ] 绑定孔升级确认、局部定位、受影响下游和有限重选按既有候选/引用契约分别补充实际窗口测试；不猜测拓扑替代。
- [ ] 记录真实参考材料和人工验收缺口，运行对应 scoped 测试。
