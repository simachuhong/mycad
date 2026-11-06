# U04 三维命令条与 T1/T2 回归 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans，先复现与取证，再在确认根因后按 TDD 修复；不重写既有几何或候选后端。

**Goal:** 在新三维外壳下统一命令步骤与接受/取消呈现，复验原草图缺陷、基础体及两种选面路径。

**Architecture:** 沿用 `ModelingCommandBar`、`FilletCommandBar`、`PartSketchWorkbench` 与 `DatumTaskDialog` 的业务状态；共同的可达控件布局继续通过 `command_strip.py` 实现。候选和一次提交仍由现有会话/Bus 保证，不把 UI 操作换成直接改模型。

**Tech Stack:** PySide6、Command Bus、现有隔离候选、pytest-qt 和 X11 虚拟窗口。

**Spec:** `docs/design/2026-11-04-unified-ui-design.md` §5.3；`docs/design/2026-11-04-unified-ui-todo.md` U04；`docs/design/solid-edge-interaction-acceptance.md` 的 ST10-S01–S05/S07/S10/S11。

## Global Constraints

- ST10 实机模式行为、真实 GPU 和用户验收仍待核对；不得将自动测试或历史探针标成手工通过。
- 命令接受只走 Bus 一次；切文档、来源修订或取消必须使旧候选失效。
- 草图未完成图元、临时曲线及自动关系不因结束/撤销被静默遗漏。
- 维持本轮已有文档会话、U02 环境设置及独立二维路径。

## Review Focus

- 未完成图元时预览/完成：不能提交被忽略的半成品。
- 自动关系吸附后：预览端点与持久点一致。
- 绘制中撤销：未完成轮廓及临时显示均清除。
- 修改来源或切换会话：过期候选无法被接受；取消不修改文档。
- 窄窗口及高 DPI：参数、接受/取消能通过滚动和键盘到达。

## Task 1 — 原 T1/T2 和基础体回归

- [ ] 按当前工作区复跑 `test_unfinished_entity_blocks_preview_and_confirm`、`test_line_preview_matches_inferred_endpoint`、`test_undo_clears_unfinished_outline`，记录逐项结果和当前源码哈希；与旧探针分开。
- [ ] 复跑 `test_resident_rectangle_entry_selects_tool_before_plane`、`test_tool_then_pick_model_face_and_lock`、`test_previewed_part_sketch_is_confirmed_once`，并覆盖先选平面再创建。
- [ ] 复跑基础体、预览取消、过期修订和确认的相关 UI 测试；任何失败按 systematic-debugging 查明根因并写失败测试后修复。

## Task 2 — 公共呈现与任务边界

- [ ] 按现有四类命令逐一列出步骤、候选状态、参数字段和接受/取消；复用 `install_command_strip(toolbar, fields, actions)` 的模型和圆角控件，不能强制同一步骤序列。
- [ ] 先测试 1024 宽窗口及高 DPI 下建模、圆角、基准和草图的状态、接受/取消可达，并验证失败/取消与重做不残留临时几何。
- [ ] 对测试证实的布局和状态不一致做最小公共呈现改动；基准与草图保留其本身合法状态机，不移动几何逻辑。
- [ ] 测试切换/修订后旧预览不能提交及确认仅一次；记录命令历史、截图和执行环境。

## Task 3 — 验收记录

- [ ] 在 `.omo/evidence/ui-redesign/` 保存测试命令、结果、源码哈希和每条 ST10 子项的证据/缺口；虚拟窗口与真实 GPU、用户手工分开。
- [ ] scoped 验证本包代码、分层规则、三维和独立二维往返；完整 ST10 和用户手工未执行项保持待复验。
