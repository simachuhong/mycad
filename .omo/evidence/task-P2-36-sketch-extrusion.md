# P2-36 — 草图驱动实体特征（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**；不是 P2-36 完成或 Solid Edge 人工验收通过。

## 交付范围

- ADR-003 释放 `feature.extrude@2`，新增 `{type: "sketch", sketch_id}` 轮廓引用。`feature.extrude@1` 的 schema 和语义不变；新版本仍接受旧参数和选面参数。
- 几何适配从历史中已提交的草图生成 BREP 面，支持线、折线、圆、圆弧和矩形组成的一个闭合外环及严格内嵌孔环；构造几何不参与实体轮廓。支持任意右手工作平面、正负距离以及 new/add/cut 布尔方式。
- 主建模命令栏增加“草图”来源，选择草图和距离后生成隔离预览；应用后按 `feature.extrude@2` 经过命令计划和 Bus 提交。取消不会追加历史。
- `feature.revolve@2` 同样支持草图引用，建模命令栏可选已提交草图、X/Y/Z 全局轴及角度；角度预览和确认经现有计划/Bus 流程。回转轴当前穿过全局原点。
- `feature.hole@2` 支持选择已提交的圆草图、目标平面实体面，以及盲孔/贯穿深度；一个草图可包含多个不同直径孔，构造圆会被忽略。交互仍先预览，确认后才经 Bus 提交。旧 `feature.hole@1` 历史保持不变，新版本也接受旧参数形状。
- 草图外轮廓现在以平面 BREP 构造，保留可供后续特征选择的解析平面端面；此修复由“草图拉伸安装板 → 第二张草图四孔贯穿 → STEP 重读比对实体数与体积”贯穿式回归覆盖。
- `.mc.json` v2 保存显式命令版本与稳定草图引用，撤销/重做和存档重开重新构造同一结果。

## 自动验证

P2-36 相关定向集合通过 **437 项**：

```text
tests/geom/test_sketch_holes.py
tests/geom/test_sketch_extrusion.py
tests/geom/test_sketch_constraints.py
tests/geom/test_sketch_commands.py
tests/geom/test_face_extrude.py
tests/geom/test_profile_workplane_prototype.py
tests/geom/test_features.py
tests/core/test_sketch_constraints.py
tests/core/test_schema_v2.py
tests/core/test_persistence.py
tests/builtin_commands/
tests/commands/
tests/ui/test_modeling_toolbar.py
tests/ui/test_modeling_interaction.py
tests/ui/test_sketch_constraint_dialog.py
tests/ui/test_sketch_editor.py
tests/test_scope_audit.py
tests/test_layering.py
tests/test_adr_docs.py
437 passed in 75.17s
```

草图孔 UI 用例另检查确认前命令历史和实体体积保持不变。改动路径 Ruff、格式检查、basedpyright 严格类型检查（0 errors / 0 warnings / 0 notes）、`uv lock --check` 和 `git diff --check` 均通过。

## 当前限制

多外环和内环实体岛明确拒绝；草图孔仅接受圆，不支持沉头/螺纹/锥度；复杂弧线混合轮廓、面附着草图、到面终止条件、直接拖动既有草图图元尚未完成。`feature.extrude@3` 现支持草图和 XY 参数截面的对称总深度拉伸；模型平面面拉伸仍为单侧范围并对对称模式明确报错。2026-10-25 的后续切片已提供通过历史编辑修订上游草图并重放下游特征的 UI，参见 [P2-34 草图历史编辑证据](task-P2-34-sketch-history-edit.md)。仍未运行全量测试，也未进行人工 Solid Edge 对比。

## 版本补充：对称拉伸自检

P2-36 补充释放 `feature.extrude@3`，新增可选 `extent_mode`，默认 `one_sided`；`symmetric` 将正 `distance` 作为总深度并以草图/XY 截面平面为中心均分。@1/@2 参数 schema 与历史语义不变；面拉伸的对称范围明确拒绝。回归覆盖 schema 默认值与旧版拒绝新字段、草图 annulus 体积/质心、XY 圆截面包围盒、非法非正深度不写历史、草图对称拉伸保存重开/undo/redo、工具栏范围序列化和面拉伸拒绝。

此行为按 Siemens Solid Edge 用户指南里的 symmetric extent 描述做桌面产品自检：范围以草图平面居中，两侧各分一半。[Siemens ST4 Modeling guide](https://support.industrysoftware.automation.siemens.com/training/se/en/ST4/pdf/mt01413-s-1040_en.pdf)。这只是参考规格核对；用户人工桌面验收仍待明日执行，不能视为 Solid Edge 操作等价或验收通过。

## 2026-10-25 未验证源码续记：多区域与嵌套岛

`make_sketch_faces` 现按轮廓嵌套深度分别生成偶数层级的实体区域，并将每个区域的直接奇数层级子轮廓作为孔；孔中的偶数层级岛会另建区域。拉伸与回转分支可接收多个区域面。旧版“多外环和内环实体岛明确拒绝”的限制已被该源码续记取代。区域实体数、彼此接触/重叠边界、复杂曲线轮廓与 OCCT 结果尚未定向验证，未运行测试或 GUI；不代表 P2-36 完成。

补充验证：更新 @3 后，P2 G 的 geom/schema/UI/persistence/scope/layering/ADR 定向集合 **463 passed**（76.09s）。新增“对称草图拉伸预览后提交” UI 交互回归随后单独通过（1 passed）；改动 Python 路径的 Ruff、格式检查、basedpyright（0 errors / 0 warnings / 0 notes）和 `git diff --check` 均通过。全量测试与真实 Solid Edge 手动对比仍未运行。

## 版本补充：构造线偏置旋转轴自检

释放 `feature.revolve@3`。全局轴分支沿用 @2 参数；新增的 `axis_reference` 只能引用回转轮廓同一草图中的构造 `LineEntity`，使用草图框架将有限线段端点映射到模型空间，再构造成回转轴。全局轴和构造线引用互斥；@1/@2 schema 与历史回放保持原样。UI 可在已选草图轮廓下选择全局轴或构造线；未选择有效线时禁止确认，预览/提交仍由原有隔离预览与 Bus 流程完成。几何回归覆盖体积、偏置轴对应质心、保存重开、undo/redo，以及同草图普通线和跨草图构造线均不写入失败历史。

设计对照 Siemens Solid Edge Ordered Revolve：官方培训指南描述先选草图，再选择草图中的虚线中心线作为轴；当前 UI 的轮廓草图构造线选择映射到此步骤。这里只完成源码和自动化自检，尚未进行 Solid Edge 人工操作对比。模型边/圆柱面轴和跨草图轴选择不在本次版本契约内。来源：[Siemens Solid Edge ST5 Fundamentals](https://support.industrysoftware.automation.siemens.com/training/se/en/ST5/pdf/mt01413-s-1050_en.pdf)。

补充验证：完整 P2 G 定向集合 **467 passed in 79.16s**；包含最新同草图轴线校验。新增的七个 schema/几何/UI 轴引用用例格式化后复跑 **7 passed in 8.70s**。改动路径 Ruff、format、basedpyright（0 errors / 0 warnings / 0 notes）和 `git diff --check` 全部通过。没有运行全仓 pytest，也没有把自动化自检表述为 Solid Edge 人工验收。

## 2026-10-25 收敛验证更新

上述验证之后，草图轮廓的多区域/嵌套岛续记以及当前建模交互已纳入全仓验证：`uv run pytest -x -q -o faulthandler_timeout=90` → **1518 passed in 308.19s**。全项目 Ruff、291 文件格式检查、basedpyright（0 errors / 0 warnings / 0 notes）和 `git diff --check` 全部通过。到面终止与多区域 BREP 的自动回归现已通过；用户桌面操作及 Solid Edge 实机比较仍待验收，复杂曲线轮廓与拓扑边界不因此宣称全覆盖。
