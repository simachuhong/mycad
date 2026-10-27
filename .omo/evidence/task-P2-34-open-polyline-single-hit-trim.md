# P2-34 — 开放多段线单交点修剪（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**。操作只修改未提交草图草稿，不表示 P2-34/P2 G 完成，也不替代 Solid Edge 桌面验收。

## 行为

- 在开放多段线的一段上，修剪区间可由一个内部交点与段端顶点界定，也可由两个内部交点界定。点击其间区间会删除这一段，不改变交点或另一边的路径。
- 若删除位于路径端部，余下部分继续是一条开放多段线并保留原 ID；若内部段剩余前后两侧，则按原顺序生成两条开放路径，前段保留原 ID，后段分配新 ID。短于两个点的碎片被省略；有有效保留片段即保留原 ID。
- 保留的原有顶点与构造属性不变。闭合路径、无交点、点击交点/顶点以及产生退化结果的操作拒绝且不写入草稿；若交点位置同时命中目标和切割线，则明确报告目标歧义。草稿撤销恢复完整原路径，Finish/Cancel 仍只有整体 `sketch.create` Bus 提交边界。

## Solid Edge 自检

Siemens 官方 [Solid Edge Fundamentals Sketching 教程](https://support.industrysoftware.automation.siemens.com/training/se/en/ST5/pdf/mt01413-s-1050_en.pdf)和 [Line2d Trim API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgeFrameworkSupport~Line2d~Trim.html)确认修剪会基于相交几何删除曲线段；教程还展示了拖过一个或多个元素的交互。MyCAD 单击删除开放路径中的一个明确区间，保留前后边段拓扑规则由自身定义；没有对 Solid Edge 多段线连接关系或桌面交互作等同声明，拖动修剪仍不支持。

## AutoCAD 工作流参照

Autodesk 官方资料显示，Trim/Extend Quick 模式可将图中对象作为候选边界，并允许单选、拖选和 Fence；修剪/延伸悬停预览及 Shift 模式切换可减少重复启动命令；PEDIT 支持 Ctrl 单击定位多段线子段。Solid Edge Extend to Next 的官方教程采用先选待延伸元素、再点近端头的交互，也允许 Ctrl 指定目标元素。MyCAD 现有切片仍是自动推断最近有效交点 + 草稿内单击编辑：有目标高亮，但没有结果预览、Shift 切换、Fence/拖选或子段 Ctrl 选择。参考来源及差异已经加入 [Solid Edge 操作验收基线](../../docs/design/solid-edge-interaction-acceptance.md)；桌面实机对照仍待用户验收，不宣称等价。

## 自动验证

- 先添加了开放路径单交点首/末端修剪与内部段切分用例。旧实现的 3 项核心回归因要求至少两个交点而失败；旧 Qt 工具仍预选目标，但点击后保留了待删除端部，界面测试失败。又核对交点本身的操作：当目标与切割线同时命中，系统按候选选择规则报目标歧义；顶点点击报告无有效区间，二者均保持原几何。
- 最终定向验证：

```text
uv run pytest tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
135 passed in 58.52s

uv run ruff check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
All checks passed!

uv run ruff format --check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
4 files already formatted

uv run basedpyright src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

手工对照步骤已更新到 [Solid Edge 操作验收基线](../../docs/design/solid-edge-interaction-acceptance.md)。未运行全仓测试或 Solid Edge 桌面流程。
