# P2-35 — DXF 草图子集交换（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**；不代表 P2-35 完成，也不代表 Solid Edge 人工验收通过。

## 本切片交付

- 注册 DXF 格式 provider，并把 DXF 草图导出接入 GUI 导出菜单及 CLI/provider 写路径。输出版本为 R2010（AC1024），单位为 mm。
- 导出单张草图中的直线、折线、圆、圆弧、矩形和构造线。MyCAD XDATA 保存草图/图元身份、矩形语义与圆弧方向；构造线写在 `MYCAD_CONSTRUCTION` 图层。
- 提供 `DxfSketchProvider.read_sketch()` / `read_sketch_dxf()` 读取 API，支持 LINE、LWPOLYLINE、CIRCLE、ARC，读取圆弧、闭合轮廓、构造图元和 MyCAD 身份。DXF 未声明受支持单位时必须显式传入单位覆盖，不推测缩放。
- `DxfExchangeReport` 明示版本、单位、图元数和未交换内容；导出状态栏、CLI/provider 调用方可显示报告。非支持图元、图层/样式状态、布局、约束、非 XY 工作平面和未导出的实体会产生说明。
- ADR-005 记录支持边界。GUI 导入经专用 DXF 读取 API 异步读取，先显示交换报告；未声明单位时弹出明确单位选择；预览拒绝不改历史；确认后以 `sketch.create` 经 `CommandBus` 写入。与当前文档草图身份冲突时会在预览前重分配并报告。

## 支持矩阵与限制

| 方向 | 支持 | 明示限制 |
|---|---|---|
| 写出 | DXF R2010；LINE、LWPOLYLINE、CIRCLE、ARC；闭合矩形以闭合 LWPOLYLINE 表示 | 单张草图；只导出草图线稿；不写约束/标注、字体、工作平面位姿或实体；导出报告列出损失 |
| 读入 API | LINE、LWPOLYLINE、CIRCLE、ARC；MyCAD 矩形/圆弧语义 XDATA；构造图层 | 不支持项跳过并报告；只读模型空间 XY 几何；未知单位需明确覆盖；不保留图层样式/显隐锁定、尺寸标注和字体 |
| GUI | DXF 导出入口和结果报告；DXF 导入、未知单位选择、导入报告预览/确认及 Bus 提交 | 尚无二维独立文档、图层属性编辑或基础尺寸标注 |

## 验证

最终 scoped 验证通过：

```text
uv run pytest tests/formats tests/app/test_composition.py tests/cli/test_builtin.py tests/ui/test_menus_toolbar.py tests/ui/test_document_lifecycle.py tests/test_notice.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
151 passed in 83.47s

uv run ruff check <changed Python paths>       # All checks passed
uv run ruff format --check <changed paths>    # 14 files already formatted
uv run basedpyright <changed Python paths>    # 0 errors, 0 warnings, 0 notes
git diff --check                               # passed
```

这组测试验证 R2010/mm 往返与身份、圆弧方向、矩形和构造线、未知单位拒绝/显式覆盖、不支持图元和图层状态的报告、单草图导出限制、GUI 导出反馈、导入预览后经 Bus 提交、拒绝预览不写入、缺省单位显式选择后的缩放、provider 注册、分层与 ADR/NOTICE 约束。未运行全量四门或真实 Solid Edge / 下游 CAD 桌面验收。

## 后续工作

完成 P2-35 仍需图层显隐/锁定/颜色/线型/线宽工作流、长度/对齐距离/角度/半径/直径标注及其单位/精度/驱动或参考语义。之后应以安装板工作流验证 DXF 下游读取与尺寸核对，并由用户人工验收。

## 2026-10-25 后续开发：图层属性与尺寸标注

本节追加记录上面的阶段性边界在后续实现中的变化；前文保留其当时状态。

- 草图图层已支持颜色、线型、线宽、显隐和锁定状态，锁定图层拒绝草稿编辑，隐藏图层不参与视口拾取/标注展示。
- `sketch.create@3` 可持久化长度、点间距离、角度、半径和直径尺寸约束。标注保存稳定图元引用、驱动/参考语义、单位制、精度和比例；旧 schema 版本在存在尺寸约束时显式拒绝降级，避免静默丢尺寸。
- PlaneGCS 求解结果和参考尺寸进入视口标签 DTO；`GLTextItem` 按当前锁定的 pyqtgraph 0.13 API 单项绘制。UI 尺寸对话框允许调整小数精度和标注比例。
- DXF R2010/mm 导出标准 `DIMENSION` 实体，XDATA 保留 MyCAD 约束 ID、几何引用和格式属性；有 MyCAD 关联的支持子集可以读回草图。无 MyCAD 引用的外部尺寸会在交换报告中说明并跳过。
- 仍未提供完整标注拖放/重定位、自动关系推断、外部 DXF 尺寸语义导入和上游模型变更后的普遍关联更新；AutoCAD/Solid Edge 下游实体读取与外观还需桌面人工验收。

本次复核命令与结果：`tests/core/test_sketch.py`、`tests/core/test_sketch_constraints.py`、`tests/core/test_viewport_protocol.py`、`tests/builtin_commands/test_specs.py`、`tests/formats/test_dxf_sketch_exchange.py` 共 91 通过；`tests/geom/test_sketch_commands.py` 8 通过；尺寸对话框与视口覆盖测试 5 通过。触及 Python 路径的 Ruff 和 basedpyright 均通过（0 errors / 0 warnings / 0 notes）。P2-35 仍 partial，不能据此标记任务完成。

收敛自检更新（2026-10-25）：最新全仓 pytest **1518 passed in 308.19s**，全树 Ruff、291 文件格式检查、basedpyright（0 errors / 0 warnings / 0 notes）及 `git diff --check` 通过。AutoCAD/Solid Edge 下游打开 DXF、测量标注外观和兼容性仍需用户桌面验收；外部 DXF 尺寸语义和泛化关联更新不在当前支持子集中。
