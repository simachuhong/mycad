# U09 二维文档属性 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans 逐项实施；测试遵守项目增量范围规则。

**Goal:** 独立二维特性页在无选中对象时显示当前文档的六项元数据，并在对象选择、元数据变化及文档切换后同步。

**Architecture:** 编辑器接受只读元数据提供函数，选中对象时保留现有特性展示；主窗口将提供函数绑定到该编辑器所属文档，在文档元数据事件及工作区恢复时刷新。沿用已有 `METADATA_KEYS` 与空值显示，不修改文档或存档。

**Tech Stack:** Python、PySide6、pytest-qt。

**Spec:** `docs/需求分析书.md` 的 F-PROP-01，以及 `docs/design/2026-11-04-unified-ui-todo.md` 的 U09 特性与环境隔离条款。

## Global Constraints

- 只读展示，不修改模型、持久化格式或命令历史。
- 只运行本改动的定向用例及直接受影响项；不运行全量测试。
- 编辑器必须读取所属文档，不能在文档切换时借用当前活动文档的值。

## Review Focus

- 缺失字段显示占位，已有空字符串和其他值按原值显示；定向测试核对两者。
- 对象选中时显示对象特性，取消后恢复文档属性；定向测试覆盖。
- 当前文档元数据变化后无选中页面刷新；定向测试覆盖。
- 切换文档后不串值，返回时读取所属文档；定向测试覆盖。
- 独立使用且没有提供文档的编辑器保留既有空选区行为；现有直接关联用例覆盖。

## Task: 二维文档特性

**Files:** `src/mycad/ui/sketch_editor.py`、`src/mycad/ui/main_window.py`、`tests/ui/test_drawing_selection_properties.py`。

- [x] 新增真实主窗口测试，检查空选区元数据、选中与取消、元数据刷新和两个二维文档往返；旧行为因缺少元数据而失败。
- [x] 为编辑器提供所属文档元数据的只读接口，并接入主窗口现有事件与恢复路径。
- [x] 新增用例和受影响的原特性页选择用例 **2 passed**；改动文件 Ruff、格式和 basedpyright 通过。设备验收待执行。
