# U12 Quick Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 支持按工作环境配置快速访问动作的添加、移除、排序和持久化，插件移除时保留可解释的失效项。

**Architecture:** 快速访问使用现有 `ActionCatalog` 中的同一 `QAction`，不复制动作状态。独立 QSettings 键保存各环境有序稳定 ID；未知 ID 以禁用占位显示并原样保留，动作重新出现后恢复。主窗口在文档/环境切换时切换列表；配置对话框编辑副本，确认后才保存和更新。

**Tech Stack:** Python、PySide6、QSettings、pytest-qt。

**Spec:** `docs/design/2026-11-04-unified-ui-todo.md` U12。

## Global Constraints

- 文件菜单按钮保留；默认新建、打开、保存、撤销、重做维持既有行为。
- 一个稳定 ID 对应同一个 QAction；不覆盖插件或猜测失效动作。
- 每个环境仅修改自己的 QAT 设置；布局重置不得删除其他环境或文档。
- 旧 QSettings 及已有工具栏/多文档状态不做破坏性迁移。

## Review Focus

- 缺失插件 ID：保留次序、禁用并解释，可重新注册恢复。
- 空列表与重复/损坏设置：空列表可保存，损坏显式回退，不能改变文档。
- 编辑取消与切换：取消不保存；不同环境和重启保持各自配置。
- 不可用动作：共享原动作的可用状态、快捷键和提示，不派发禁用命令。
- 工具栏重建和 200% 缩放：配置入口及保留动作可达，应用菜单持续可用。

### Task 1: QAT 状态与编辑器

**Files:** `src/mycad/ui/action_catalog.py`, 新建 `src/mycad/ui/quick_access.py`, 新建 `tests/ui/test_quick_access.py`。

- [x] 用 QSettings 实现带环境的有序 ID 保存、读取、空列表、坏数据回退和缺失动作占位，保留原始 ID。
- [x] 在配置对话框中添加/移除/上下排序；编辑副本，取消不写入。
- [x] 用共享 QAction 验证状态同步及插件移除/重现；运行 scoped lint、format、类型及测试。

### Task 2: 主窗口与跨环境

**Files:** `src/mycad/ui/main_window.py`, `tests/ui/test_quick_access.py`, `tests/ui/test_workspace_layout.py`。

- [x] 将已有快速访问区域连接控制器，保留文件菜单和默认动作；配置入口清晰且不占用动作 ID。
- [x] 跟随首页、零件、零件草图、独立二维和工程图切换列表；重启和旧设置不改变其他环境。
- [x] 测试重置、插件失效及重新注册、文档/布局隔离、200% 缩放的实际窗口。

### Task 3: 命令查找与插件入口

- [x] 为可用动作和注册插件命令显示所属组与当前状态，动作经目录复用；无插件或插件移除时不模拟能力。
- [x] scoped 回归后记录环境、实际截图及仍缺少的人工验收。

### Task 4: 环境化辅助面板状态

**Files:** `src/mycad/ui/workspace_layout.py`, `src/mycad/ui/workspace_console.py`, `src/mycad/ui/main_window.py`, `tests/ui/test_workspace_console.py`。

- [x] 按环境持久化展开状态、活动标签及高度；坏值回退为信息页收起，当前环境重置只清除自己的辅助面板状态。
- [x] 切换环境先保存再恢复；程序化恢复不覆盖其他环境设置，不销毁 CLI/AI 输入草稿。
- [x] 测试零件/独立二维往返、重启、损坏设置、独立二维命令行与未连接 AI 行为；运行 scoped 检查。
