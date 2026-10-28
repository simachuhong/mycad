# Drawing Annotation Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution, with checkbox steps.

**Goal:** 工程图可见的尺寸入口和可保存/出图的图中自由文字。
**Architecture:** DrawingNote经Bus重放；共享PaperText出图；画布内文字编辑器，主工具条菜单和右栏创建入口。
**Tech Stack:** Python/PySide6/现有DXF/PDF。
**Spec:** docs/superpowers/specs/2026-10-28-drawing-annotation-entry-design.md

## Global Constraints
- core禁Qt/CAD/numpy，ui禁geom；Bus唯一写入，旧规格不变，档案v3。
- 文字属纸张、单位mm；纯文本，Esc取消、Ctrl+Enter提交、双击/拖动/Delete，保存保护。
- 保留当前分支和用户GUI/Logo素材。

## Review Focus
- 切文件/纸张不得写错文档：Task2 UI测试。
- 编辑器内Delete/Enter不能误删或提交其他对象：Task2 UI测试。
- 中文、多行、DXF控制字符不能当格式解释：Task1/2导出测试。
- 字高不随视图比例变化，文本增删不触发HLR：Task1测试。
- 隐藏次工具条后仍可创建尺寸：Task2入口测试。

### Task 1: 可重放纸面文字与输出
**Files:** core/drawing.py、drawing_codec.py、drawing_projection.py、drawing_paper.py、document_kinds.py、document.py；builtin_commands/drawing_specs.py；geom/kernel.py；formats/drawing_export.py；tests/core/test_drawing_notes.py。
**Interfaces:** DrawingNote(note_id, sheet_id, text, position_mm, height_mm=3.5, layer='TEXT')；DrawingState.notes；DrawingScene.notes；drawing.note.create/update/delete v1。
- [x] RED：文字create/update/delete/撤销/roundtrip、删纸级联、文字布局不改source指纹、旧命令仍可用；空文本/非法字高拒绝。
- [x] 实现中立模型/codec/规格/Bus接入和PaperText共享输出。
- [x] `uv run pytest tests/core/test_drawing_notes.py tests/core/test_drawing_model.py tests/core/test_drawing_archive.py tests/formats/test_drawing_export.py -q`通过；提交。

### Task 2: 入口与图中编辑
**Files:** ui/drawing_annotation_tools.py、drawing_workbench.py、drawing_canvas.py；新增ui/drawing_note_tools.py；tests/ui/test_drawing_note_tools.py；docs/工程图操作指南.md。
**Interfaces:** DrawingNoteTools.pending/begin/edit/cancel/preview；画布note_selected/edit_requested/dragged/delete_requested信号；工作区整合互斥、保存保护。
- [x] RED：主工具尺寸和文本入口、右栏入口、画布创建中文多行/取消/双击/拖动/Delete/撤销，切文件取消，DXF/PDF文字。
- [x] 实现菜单/完整图标按钮/右侧创建按钮、图中编辑器与持久操作。
- [x] `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_drawing_note_tools.py tests/ui/test_drawing_annotations.py tests/ui/test_sketch_paper_view.py tests/ui/test_drawing_pdf.py tests/ui/test_drawing_start.py tests/ui/test_workspace_tabs.py tests/test_layering.py -q`通过；差异lint/format/type，截图验收；提交。
- [x] 最终独立审查并保存证据，保留本地分支。
