# U13 Integration and Adaptation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对各工作环境进行可复现的跨尺寸/DPI 和任务链检查，保留无法自动替代的用户与参考实机验收。

**Architecture:** 使用 Xvfb 下的 xcb 窗口和软件 OpenGL 分别模拟物理屏幕及 Qt 缩放；逐环境采集窗口、逻辑尺寸与关键控件可达性，结合分包任务链测试定位问题。自动结果不能替代真实桌面、Windows、输入法或用户确认。

**Tech Stack:** PySide6、xcb/Xvfb、pytest-qt、ruff、basedpyright。

**Spec:** `docs/design/2026-11-04-unified-ui-todo.md` U13。

## Global Constraints

- 只在最终集成时运行一次全量四门，之前按改动范围复验。
- 不把自动截图或模拟环境记录为用户验收；标明版本、环境、限制与待办。
- 不修改用户已有文档与设置；验证使用临时 QSettings、会话与测试文档。
- 不启用尚未实现的装配、同步建模、曲面、PMI 功能。

## Review Focus

- 实际逻辑面积变小时确认/取消及主导航不能落在不可达区域。
- 工作区切换不得丢草稿、跨文档模型或设置；二/三维及工程图独立。
- 非 ASCII 文本、失败消息和缺失插件不能导致控件重叠或误报可用。
- 显式保存、取消和后台文档状态保持一致；不覆盖原数据。
- Linux 模拟结果不能推断 Windows、真实输入法及用户认可。

### Task 1: xcb 窗口/DPI 矩阵

- [x] 对 1024×768、1366×768、1920×1080 × 100%/125%/150%/200% 分别采集首页、二维、工程图和零件窗口及逻辑面积；检查可见和可滚动操作入口。
- [x] 若发现不可达、遮挡或截断导致无法操作，先写针对性测试、修复、复跑相关组合。
- [x] 记录实际 Xvfb/xcb、Qt 缩放、软件 OpenGL 与截图；不宣称实体显示器验收。

### Task 2: 任务链和差异化回归

- [x] 执行首页三入口、文档保存/取消、二维制图、零件草图/特征、绑定孔修复和工程图来源更新相关 scoped 测试。
- [x] 汇总未完成的 ST10/AutoCAD 实机行为、输入法、Windows 和用户确认，不凭截图推断通过。

### Task 3: 最终集成门

- [ ] 待 U01–U12 必要范围完成后，按项目规则运行全量 lint、format、strict typing 与 pytest 各一次；失败按范围修复和复跑。
- [ ] 用户逐环境验收后更新 U13，任何缺失均不勾选完整验收。
