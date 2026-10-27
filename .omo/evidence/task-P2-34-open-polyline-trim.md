# P2-34 — 开放多段线段修剪（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**。编辑只作用于未提交草稿，不表示 P2-34、P2 G 或 Solid Edge 人工验收已完成。

## 实现与边界

- “修剪”悬停高亮唯一开放多段线段；几何核心可将直线、开放多段线、矩形边、圆或有效扫掠范围内的圆弧作为切割对象。构造切割几何不参与。
- 只允许在同一开放多段线段上存在至少两个唯一内部交点，且点击处严格位于两个交点之间时执行。相切/重复交点去重；交点、端部区间、仅一个交点、无交点和目标歧义均拒绝且不修改草稿。
- 删除区间后将路径变成前/后两条开放多段线，保留目标段之前/之后的全部顶点与构造状态；前缀沿原路径顺序保留旧 `entity_id`，后缀取得新 ID。闭合多段线明确拒绝。
- 操作记录为一个草稿撤销快照；Finish/Cancel 仍保持已有的一条 `sketch.create` Bus 提交边界。

## Solid Edge 对照

Siemens 官方 [Line2d Trim API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgeFrameworkSupport~Line2d~Trim.html)描述了按交点修剪线段，Solid Edge 草图教程也展示了拖动 Trim 穿过多个元素。MyCAD 此切片采用单击区间并只操作开放多段线的单一线段；没有验证 Solid Edge 多段线拓扑、约束迁移或相同 UI 手势，因此不声称行为等同。桌面实机比较待用户验收。

## 自动验证

- 先添加开放路径与闭合路径测试；它们因核心只识别直线/圆/圆弧而失败。再加入真实 Qt 悬停/点击/撤销回归，确认旧 UI 不会预选多段线；实现后回归转绿。
- 核心回归覆盖多顶点前缀保留、身份/构造属性、有限直线/圆/有效扫掠圆弧切割器、闭合路径拒绝、无交点拒绝；Qt 回归覆盖悬停、区间删除、身份与撤销。
- 最终定向验证：

```text
uv run pytest tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
125 passed in 57.20s

uv run ruff check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
All checks passed!

uv run ruff format --check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
4 files already formatted

uv run basedpyright src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

跨多个多段线段的连续删除、端部单交点修剪、闭合多段线修剪和 Solid Edge 桌面验收仍未覆盖。
