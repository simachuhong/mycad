# P2-34 — 草稿曲线修剪扩展（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**。这是既有草稿编辑器的增量切片，不表示 P2-34、P2 G 或 Solid Edge 人工验收已完成。

## 实现范围

- `trim_curve_at` 以唯一命中的草稿直线、完整圆或圆弧为目标，按鼠标所点交点区间删除曲线。直线切割器包括普通线、折线段和矩形边；圆/圆弧切割器按两条曲线的有效范围求交；构造几何不参与切割。
- 完整圆修剪后转为保留区段对应的圆弧；圆弧修剪保留原有顺/逆方向。首个幸存区段保留目标 `entity_id`，额外区段取得新 UUID。圆/圆弧没有足够唯一交点、相切、点击端点/交点、目标歧义及非法坐标均拒绝且不改变草稿。
- 画布修剪悬停高亮覆盖直线、圆和圆弧；“分割直线”仅预选直线，避免显示不可执行的圆/弧目标。草稿撤销仍恢复原始完整圆/圆弧与选择状态，完成/取消仍遵守单条 `sketch.create` 写入边界。

## 自检与限制

Siemens 官方 [Circle2d Trim API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgeFrameworkSupport~Circle2d~Trim.html) 将切割对象交点与方向点作为修剪输入；[Arc2d 成员](https://support.industrysoftware.automation.siemens.com/trainings/se/107/api/SolidEdgeFrameworkSupport~Arc2d_members.html)也列有 Trim 方法。MyCAD 此切片覆盖圆/弧曲线求交，但只支持单击并从草稿自动查找切割对象；Solid Edge 文档还描述拖动过多个元素及显式切割对象。实机选择、预览、拖动和视觉反馈比较仍待用户验收。

仍未覆盖拖动修剪、修剪多段线内部段、圆/圆弧延伸、选择切割器/多目标操作、复杂重叠/共圆拓扑处理、已提交约束草图编辑及约束引用迁移。

## 自动验证

本切片新增回归覆盖完整圆与两条直线/另一圆求交、圆弧按曲线有效域过滤交点、构造切割器排除、顺/逆扫掠方向与分段身份，以及 Qt 画布上的圆修剪/undo 和分割工具的直线限定预选。另有重复/歧义、无交点、切点与端点拒绝用例。

```text
uv run pytest tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
110 passed in 50.05s

uv run ruff check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
All checks passed

uv run ruff format --check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
4 files already formatted

uv run basedpyright src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

人工验收步骤见 [Solid Edge 操作验收基线](../../docs/design/solid-edge-interaction-acceptance.md) 的二维曲线修剪段。未执行全仓测试，也未运行 Solid Edge 桌面流程。

2026-10-25 follow-up adds direction-preserving arc endpoint extension; see [arc extension evidence](task-P2-34-sketch-curve-extension.md). The extension gap above was accurate for this trim-only slice.
