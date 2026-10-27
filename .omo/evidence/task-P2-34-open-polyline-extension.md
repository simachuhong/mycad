# P2-34 — 开放多段线端点延伸（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**。这次只扩展尚未提交草稿的几何编辑；不表示 P2-34、P2 G 或 Solid Edge 人工验收完成。

## 实现范围与边界

- “延伸”悬停可预选开放多段线的第一个/最后一个端点。单击后沿现有首段/末段方向延伸到最近的非构造有限直线段交点；直线段切割器包含普通直线、折线段和矩形边。
- 成功后只替换路径的首点或末点，保留顶点顺序、中间顶点、`entity_id` 和构造状态；仍是一条开放多段线，不拆成松散线段。草稿撤销还原整条原路径，Finish/Cancel 与既有一次 `sketch.create` Bus 边界不变。
- 闭合路径、内部顶点/段、构造切割器、无向外交点或不唯一端点均拒绝且不修改草稿。此切片不支持内部段、闭合路径、曲线切割器或直接编辑已提交/受约束草图。

## Solid Edge 自检

Siemens 官方 Solid Edge Fundamentals 草图教程描述了把开放线延伸到下一几何；官方 [Line2d Extend API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgeFrameworkSupport~Line2d~Extend.html)说明 Extend 将开放图元延至指定位置，[Arc2d 成员 API](https://support.industrysoftware.automation.siemens.com/trainings/se/107/api/SolidEdgeFrameworkSupport~Arc2d_members.html)也列出 Extend。MyCAD 延续了“开放曲线端点到相交几何”的操作方向，但当前只自动选最近有限直线段，不要求显式选择目标对象，也未核对约束迁移、LineString2d 行为或 Solid Edge 桌面交互，不能宣称等同。参见 [Solid Edge Fundamentals Sketching](https://support.industrysoftware.automation.siemens.com/training/se/en/ST4/pdf/spse01510-s-1040_en.pdf)。

## 自动验证

- TDD 先行：核心新增用例在旧实现上按预期失败（开放路径端点不被识别、闭合路径失败原因不符合契约）；Qt 回归因旧 UI 不高亮开放路径端点而失败。完成实现后新增核心与 UI 用例转绿。
- 核心覆盖首端/末端、最近向外交点、保留路径身份/构造属性/中间顶点、闭合路径/内部点击/无交点/构造切割器拒绝及输入不可变。Qt 覆盖真实画布悬停、鼠标点击与撤销。
- 最终定向验证：

```text
uv run pytest tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
129 passed in 61.24s

uv run ruff check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
All checks passed!

uv run ruff format --check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
4 files already formatted

uv run basedpyright src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

未运行全仓测试或 Solid Edge 桌面流程；人工步骤已补到 [Solid Edge 操作验收基线](../../docs/design/solid-edge-interaction-acceptance.md)。
