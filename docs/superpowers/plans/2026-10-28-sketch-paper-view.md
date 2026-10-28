# Sketch Paper View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将已提交二维草图作为关联平面视图在工程图中直接放置、标注、保存和输出。
**Architecture:** 扩展视图来源及稳定图元引用；纯core将Sketch转成ProjectionResult，既有异步三维路径保留。两类来源共享图纸、命令历史、场景、标注与输出。
**Tech Stack:** Python、PySide6、现有CommandBus、ezdxf/QPdfWriter。
**Spec:** docs/superpowers/specs/2026-10-28-sketch-paper-view-design.md

## Global Constraints

- core不引CAD/Qt/numpy；ui不引geom。持久写入经Bus；旧v1命令保留，扩展view/annotation create/update为v2。
- 单文档已提交草图来源；局部U/V毫米；构造/隐藏图元不显示。
- 草图驱动标注不复制，纸上新增标注为参考尺寸；没有实体时不得生成实体投影。
- 保留当前checkout；前轮整改已checkpoint为3a887cf；不重启用户实例。

## Review Focus

- drawing2d不能利用开放的工程命令获得实体来源；Task1负例覆盖。
- 同一图纸混合两种来源、层可见性变更，不能出图旧结果；Task3覆盖。
- 放置期间切文档或源草图改变，不能提交错误来源；Task3覆盖。
- 样条/负向圆弧/闭合折线必须保留精确几何；Task2覆盖。
- 修改源长度后标注真实值更新，纸面比例不改变测量值；Task4覆盖。

### Task 1: 来源、命令及档案
**Files:** core/drawing.py、drawing_codec.py、drawing_references.py、document_kinds.py；builtin_commands/drawing_specs.py；geom/kernel.py；tests/core/test_sketch_paper_archive.py。
**Interfaces:** SourceBinding(kind='sketch', sketch_id=str)；DrawingGeometryReference(kind='sketch_entity', sketch_id=str, entity_id=str)；create/update v2参数；drawing2d可保存工程图。
- [x] 编写并运行失败测试：.my2d无实体下创建草图视图、roundtrip/undo；不存在来源及实体来源拒绝；v1拒绝新来源。
- [x] 实现上述数据、校验、v2规格与白名单；保持旧记录不变。
- [x] `uv run pytest tests/core/test_sketch_paper_archive.py tests/core/test_drawing_archive.py tests/core/test_drawing_model.py -q` → PASS；提交。

### Task 2: 精确二维转换与标注来源
**Files:** 新core/drawing_sketch.py；core/drawing_projection.py、drawing_references.py；tests/core/test_drawing_sketch.py。
**Interfaces:** project_sketch(sketch: Sketch, request: DrawingProjectionRequest) -> ProjectionResult；request增加sketch_id/source。
- [x] 编写并运行失败测试：六种几何、层隐藏、负圆弧、精确样条、源线长40→60后关联尺寸60。
- [x] 实现纯二维曲线转换及稳定图元/段引用，保留曲线类型，允许现有视图变为空可见集。
- [x] `uv run pytest tests/core/test_drawing_sketch.py tests/ui/test_drawing_annotations.py -q` → PASS；提交。

### Task 3: 工作区入口与结果更新
**Files:** ui/drawing_workbench.py、drawing_tools.py、drawing_updates.py；geom/drawing_worker.py；tests/ui/test_sketch_paper_view.py、test_drawing_start.py。
**Interfaces:** ViewPlacement(source=SourceBinding)只为sketch放置单视图；ProjectionUpdates.sync接收sketch_ids映射，begin按source过滤；begin_sketch_placement从右侧选定草图开始。
- [x] 编写并运行失败测试：无实体.my2d入口→预览→点击→Enter，Esc不提交、源变化暂停、切文件清理。
- [x] 接通草图选择与自动建纸；二维直接转换、三维原工作进程；同一套结果校验和输出限制。
- [x] `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_sketch_paper_view.py tests/ui/test_drawing_start.py tests/ui/test_drawing_views.py tests/ui/test_drawing_updates.py tests/ui/test_workspace_tabs.py -q` → PASS；提交。

### Task 4: 综合验收与用户文档
**Files:** tests/ui/test_sketch_paper_view.py；docs/工程图操作指南.md；.omo/evidence/sketch-paper-view/。
- [x] 添加并运行失败集成测试：源长度修改→纸上参考尺寸更新→保存重开→DXF/PDF，1:2时长度60的纸上线长30。
- [x] 修复集成缺口，同步操作说明与旧范围断言；记录正常/窄窗口截图。
- [x] 运行涉及core/commands/archive/UI/export及layering的scoped回归与lint/format/type；结果PASS。
- [x] 提交；按executing-plans完成一次全范围独立审查，必要修复后复核并保存验收记录。
