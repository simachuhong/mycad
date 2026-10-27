# P2-34 — 开放多段线段分割（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**。本增量扩展草稿分割，不表示 P2-34、P2 G 或 Solid Edge 人工验收已完成。

## 实现与边界

- 分割工具改名为“分割”，可悬停预选独立直线或多段线中的唯一线段。
- 单击靠近目标线段时，几何核心选择距点击最近的内部有限线段交点；等距交点、端点交点、无交点和目标歧义均拒绝且不改变输入。
- 开放多段线在内部线段处分割后，前缀（含原先在目标段之前的所有顶点）保留原 `entity_id`，后缀取得新 ID；构造属性保留。其余图元相对顺序不变。
- 闭合多段线明确拒绝分割，不修改草稿。草稿撤销恢复整个原多段线；草图完成/取消仍维持原单条 `sketch.create` Bus 边界。

## Solid Edge 对照

Siemens 的官方 [Line2d.SplitAtPoint API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgeFrameworkSupport~Line2d~SplitAtPoint.html)说明可在给定点分割引用对象；[Line2d 成员表](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgeFrameworkSupport~Line2d_members.html)列出 `SplitAtPoint`，并说明闭合 BSplineCurve2d 使用 `SplitAtPoints`。该资料支持分割功能方向，但不能据此断言 MyCAD 的多段线片段身份、构造状态、闭合轮廓策略或交互步骤等同 Solid Edge。桌面实机视觉与操作对照仍待用户验收。

## 自动验证

- 先添加两个核心回归，确认其因 `split_entity_at` 尚不存在而失败；实现后两项通过。
- 真实 Qt 画布回归覆盖独立直线分割、开放多段线段悬停预选/分割/撤销，以及圆弧目标不被错误预选。
- 最终定向回归：

```text
uv run pytest tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
120 passed in 53.44s

uv run ruff check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
All checks passed!

uv run ruff format --check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
4 files already formatted

uv run basedpyright src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

完整 Solid Edge 手工测试仍待用户验收；闭合多段线分割和多段线修剪/延伸未实现。
