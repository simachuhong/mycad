# P2-34 — 草稿直线修剪、延伸与分割（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**；本记录不表示 P2-34/P2 G 完成或 Solid Edge 人工验收通过。

## 本切片交付

- 草图绘制窗口增加“修剪直线”工具。悬停在唯一可选直线时以青色加粗预选；单击交点之间要移除的区段后，画布立即显示结果并留在修剪工具。
- 仅以独立直线为目标；普通直线、折线段和矩形边可提供切割交点。构造线不作为切割边。圆/圆弧及多段线内部边段暂不作为修剪目标。
- 点击交点之间的区段会移除该区间，保留其余区段。原 `entity_id` 始终分配给原线方向上的第一个幸存片段；额外幸存片段获取全新 UUID。不会静默将旧身份转给切割线或无关图元。
- 新增“延伸直线”工具。悬停在唯一端点目标上会预选整条直线；单击端点后沿该端点外侧延长到最近的非构造普通直线、折线段或矩形边交点，原 `entity_id` 保持不变。只命中端点、只选择唯一目标，内部点击或没有向外交点时拒绝且不改草稿。
- 新增“分割直线”工具。悬停时预选唯一目标直线，点击位置决定采用最近的内部直线交点；将目标分为两条共享端点的直线，第一段保留原 ID，第二段使用新 ID。等距交点拒绝操作，要求移动点击位置消除歧义。
- 点在端点/交点、没有内部交点或目标选择有歧义时拒绝操作，显示原因且保持草稿几何不变。
- 操作限于未提交的草稿；完成草图仍通过原有 `sketch.create` Bus 命令一次提交，取消草稿不写历史。已提交、带约束的草图暂不提供这项编辑。

## 自动验证

```text
uv run pytest tests/core/test_sketch_edit.py tests/core/test_sketch.py tests/core/test_sketch_constraints.py tests/ui/test_sketch_editor.py tests/ui/test_sketch_constraint_dialog.py tests/ui/test_history_edit.py tests/geom/test_sketch_commands.py tests/geom/test_sketch_constraints.py tests/geom/test_sketch_extrusion.py tests/geom/test_sketch_holes.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
165 passed in 54.91s

uv run ruff check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
All checks passed

uv run ruff format --check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
4 files already formatted

uv run basedpyright src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

没有运行全仓测试或 Solid Edge 实机流程。自动用例包含坐标级修剪/延伸/分割交点、删除单侧与中段、身份保留/新 ID、反向线方向、延伸最近交点、分割最近交点与等距拒绝、构造线排除、歧义/缺少交点拒绝，以及真实 Qt 画布鼠标悬停与点击。

## 明日人工验收

按 [Solid Edge 操作验收基线](../../docs/design/solid-edge-interaction-acceptance.md) 中“二维直线修剪”步骤对照同一草图操作，并记录 Solid Edge 版本、MyCAD 分辨率/缩放、鼠标操作、误选恢复和保存重开结果。重点观察高亮是否清晰、命令状态是否可辨、一次点击是否移除符合设计意图的线段，以及两端延伸选择步骤是否清楚。圆弧修剪、已提交草图编辑和约束引用修复仍是后续任务。

产品对照资料：[Solid Edge Fundamentals ST5 草图教程](https://support.industrysoftware.automation.siemens.com/training/se/en/ST5/pdf/mt01413-s-1050_en.pdf)说明 Trim 可拖过一个或多个线段；[Line2d Trim API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgeFrameworkSupport~Line2d~Trim.html)说明方向点决定交点间的修剪区段。当前 MyCAD 修剪为单击单条直线，拖动多段、显式选择切割对象和弧线边界仍有差距；延伸当前自动选择端点外侧最近交点，实际 Solid Edge 端点与切割对象选择流程仍待人工比较。

2026-10-25 follow-up expands trim targets to circles/arcs and supports circle/arc intersections; split preview is now line-only. The earlier line-only scope and test results above are historical. See [curve trim follow-up](task-P2-34-sketch-curve-trim.md) for current behavior and validation.

2026-10-25 follow-up also extends standalone circular arc endpoints with nearest eligible intersections while preserving sweep direction; see [arc extension evidence](task-P2-34-sketch-curve-extension.md). Straight-line extension remains limited to finite straight-segment cutters.
