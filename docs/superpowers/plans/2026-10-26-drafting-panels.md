# Drafting Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现已确认的左侧图形导航、右侧可浮动参数面板。
**Architecture:** 内嵌 QMainWindow 管理两个命名 Dock，与现有工具栏共用布局持久化。独立 SketchNavigator 负责树显示和选择信号，编辑器负责画布权限与已有尺寸编辑入口。
**Tech Stack:** Python / PySide6 / pytest-qt
**Spec:** docs/superpowers/specs/2026-10-26-drafting-panels-design.md

## Global Constraints
只改 UI 及测试、文档；保留 Bus 和模型边界；不重启用户测试进程；当前分支有未提交前置工作，不整体提交或重置。

## Review Focus
- 浮动面板在二维隐藏后不遗留窗口，返回恢复。
- 新增 Dock 与旧工具栏存储状态兼容。
- 导航不能选择隐藏/冻结/异平面/仅参照对象。
- 未完成图元、尺寸编辑、变换手势不会被导航取消。
- 选择和树内容更新不会丢失展开状态、焦点或增加模型历史。

### Task 1: Dockable parameter workspace
**Files:** Modify src/mycad/ui/sketch_editor.py; Test tests/ui/test_drafting_panels.py
**Interfaces:** Produces parameter_dock, parameter_tabs; toolbar_layout_state()/restore_toolbar_layout() include Dock state.
- [x] Write tests for default right Dock, floating/close/reopen, hide/show, reset, state roundtrip and parameter pages.
- [x] Run scoped tests and observe missing Dock failures.
- [x] Replace fixed body panel with named QDockWidget, group parameters into three tabs, add menu actions and include Dock in suspension/reset.
- [x] Run tests and scoped lint/type checks.

### Task 2: Graphical navigation and integration
**Files:** Create src/mycad/ui/sketch_navigation.py; Modify src/mycad/ui/sketch_editor.py; Test tests/ui/test_drafting_panels.py and tests/ui/test_toolbar_workspaces.py
**Interfaces:** Consumes the shared Dock lifecycle. Produces navigation_dock and navigator, bidirectional entity/constraint selection and inline dimension edit on activation.
- [x] Write tests for selection, constraint highlighting/editing, hidden/frozen/offplane/reference restrictions, pending commands, tree expansion, update/undo and layout through commit/recreation.
- [x] Observe RED before implementing the navigator.
- [x] Implement navigator, wire safe editor selection and canvas highlight/synchronization.
- [x] Run focused Qt tests, layering test, scoped lint/format/type checks; inspect rendered desktop.
- [x] Fresh independent review and fix important findings with RED/GREEN tests.
- [x] Final integration gates once, evidence and handoff.
