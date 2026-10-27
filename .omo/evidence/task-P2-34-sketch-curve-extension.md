# P2-34 — 圆弧端点延伸（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**。此切片补充草稿编辑器，不表示 P2-34/P2 G 完成或 Solid Edge 人工验收通过。

## 实现范围

- 新“延伸”工具支持独立直线和圆弧的端点。直线沿原有行为延伸到端点方向最近的非构造有限直线段交点；圆弧沿原顺/逆扫掠方向延伸到最近的范围外交点，切割对象可为非构造有限直线段、圆或有效范围内的圆弧。
- 鼠标命中必须对应唯一端点。完整圆、多段线内部段、曲线内部点击、无交点、等距交点和会使弧扫掠达到整圆的操作拒绝且不修改草稿。成功后保留原 `entity_id` 与圆弧方向。
- 圆弧端点使用画布屏幕空间预选；工具名称调整为“延伸”以覆盖线与弧。草稿 undo 仍恢复原实体；完成/取消不改变单次 `sketch.create` Bus 写入边界。

## Solid Edge 自检

Siemens 官方 [Arc2d 成员 API](https://support.industrysoftware.automation.siemens.com/trainings/se/107/api/SolidEdgeFrameworkSupport~Arc2d_members.html)列出 Extend 方法，说明圆弧属于可延伸的二维图元。MyCAD 的核心几何意图相符，但界面仍是点击端点并自动选最近交点，不提供切割对象候选、拖动或动态预览；Solid Edge 实机端点选择与失败恢复仍待用户验收。

当前有界范围：直线目标仍只接受有限直线段切割器；圆弧目标可接受有限直线段、圆和有效范围内的圆弧；完整圆无端点。多段线内部边段和已提交/带约束草图的就地编辑尚未实现。

## 自动验证

```text
uv run pytest tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
115 passed in 50.83s

uv run ruff check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
All checks passed

uv run ruff format --check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
4 files already formatted

uv run basedpyright src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

自动用例覆盖直线既有行为、逆时针弧起点和顺时针弧终点延伸、最近交点、无交点与整圆拒绝、身份/方向保持，以及真实 Qt 圆弧绘制、悬停预选和点击延伸。未运行全仓测试或 Solid Edge 桌面流程。
