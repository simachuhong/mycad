# Drawing Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 内置 GB/ISO 模板，支持其他标准 DXF 模板导入和跨电脑存档。
**Architecture:** 模板是纯数据快照，经 sheet 命令写入；模板库与 DXF 解析在 formats，Qt 操作在 ui；共享纸面渲染用于预览与导出。
**Tech Stack:** Python 3.12+, stdlib, ezdxf, PySide6, pytest。
**Spec:** docs/superpowers/specs/2026-10-28-drawing-templates-design.md

## Global Constraints

- core 仅 stdlib；DXF 解析在 formats；Qt 界面在 ui；保持零类型抑制。
- 新增 sheet 命令 v2 接受嵌入模板，v1 不改变语义。
- 无依赖升级，沿用现有 ezdxf/PySide6。
- 复用当前 codex 分支工作区，保留用户未跟踪资源。

## Review Focus

- 外部 DXF 单位未知或存在不可支持实体：明确阻止并提示，不静默丢失。
- 存档打开时外部模板文件已删除：仍完整重放。
- 切换模板与修改标题：不丢失其他已填写字段。
- 长标题或旋转文字：预览与两种导出一致，不溢出标题栏。
- 自定义幅面和模板库坏文件：不被纸张下拉框偷偷替换，不阻止内置模板。

### Task 1: 模板模型、内置库与存档

**Files:** core/drawing_templates.py（新）；core/drawing.py、drawing_codec.py、drawing_projection.py、drawing_paper.py；builtin_commands/drawing_specs.py；tests/core/test_drawing_templates.py（新）。
**Interfaces:** DrawingTemplate.to_mapping/from_mapping；builtin_template(standard, paper, landscape, projection_angle)；DrawingSheet.template；DrawingScene.template。
- [x] 写并运行内置 A0–A4、边距、模板验证、sheet v2 存档/undo/redo 测试，确认缺实现而失败。
- [x] 实现模板图元/字段、内置模板和嵌入式序列化；保留旧图纸行为。
- [x] 跑 scoped core 测试、ruff、basedpyright，预期全绿。

### Task 2: DXF 导入与用户模板库

**Files:** formats/drawing_templates.py（新）；tests/formats/test_drawing_templates.py（新）。
**Interfaces:** import_dxf_template(path, name, size_mm, layout, unit, offset_mm) -> DrawingTemplate；TemplateLibrary.load/save。
- [x] 写并运行真实 DXF 的单位、图块、属性、旋转、拒绝不支持实体和库损坏测试。
- [x] 实现 import_dxf_template 和原子 JSON 库保存；错误保留原库文件。
- [x] 跑 scoped formats 测试与四门检查，预期全绿。

### Task 3: 界面、共享渲染与文档

**Files:** ui/drawing_templates.py（新）；ui/drawing_workbench.py、drawing_render.py；formats/drawing_export.py；tests/ui/test_drawing_templates.py（新）；README.md、docs/工程图操作指南.md。
**Interfaces:** DrawingTemplatePanel 选择/字段/导入预览；共享 PaperText 旋转和宽度属性。
- [x] 写并运行 UI 模板选择、字段保留、导入取消、自定义幅面和 PDF/DXF 输出测试。
- [x] 实现模板面板和导入对话框，接入 sheet 命令，统一纸面绘制。
- [x] 跑 scoped UI 测试，生成截图与 PDF 进行视觉检查，更新操作文档。
- [x] 最终全量四门各跑一次，独立代码审查并修复有依据的问题。

最终验证见 `.omo/evidence/drawing-templates/acceptance.md`：77 项相关测试通过；全量 13 项既有失败经原始 HEAD 对照复现，另 3 项已在最终代码上复测通过。
