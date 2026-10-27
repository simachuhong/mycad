# P2-34 — 草图草稿变换与阵列（阶段性证据）

日期：2026-10-25。状态：partial，仍在开发。本切片增加草稿变换能力，不表示 P2-34、P2 G 或 Solid Edge 人工验收已完成。

## 实现范围

- 草图编辑器增加“选择元素”工具；单击预选元素，Ctrl+单击多选或取消选择，选中与悬停元素高亮。命中半径固定为 12 屏幕像素，等距歧义时拒绝并提示缩放/调整点击位置。
- 提供移动、复制、旋转、水平/竖直轴镜像、线性阵列、环形阵列和带符号偏移。输入采用毫米坐标与角度字段；UI 的线性/环形阵列总数包含源元素，范围为 2–1000；完整 360° 环阵不重复终点，部分角阵包含起止角。
- 移动/旋转/镜像保留实体身份；副本和阵列项使用新 UUID；构造标记、圆弧扫掠方向和闭合多段线一并保留。任意角旋转矩形转换为闭合多段线，正交旋转与镜像仍可表示为矩形。
- 偏移支持直线、圆、圆弧、开/闭折线和矩形。折线转角使用斜接；短边、折返、过尖角、过大闭合轮廓偏移及自交/退化结果会拒绝并保持输入不变。圆偏移正值向外；圆弧按扫掠方向解释左侧偏移。
- 撤销栈保存草稿几何和选择状态，绘图、线编辑、变换和阵列都可逐步恢复。取消草图不写文档；完成草图时仍只走一条 sketch.create Bus 命令。
- 草图几何操作位于 core，不引入 Qt/CAD 后端；UI 只提供选择、参数和草稿显示。

## Solid Edge 自检

Siemens Solid Edge Fundamentals 将 2D 移动、复制、旋转、镜像、缩放和拉伸列为草图操作；Solid Edge 二维环阵 API 提供圆/弧定义的阵列入口。MyCAD 实现了其中移动、复制、旋转、镜像、偏移和基础线性/环形阵列的精确参数子集。

本轮没有 Solid Edge 桌面实测。当前仍缺动态操纵手柄、拖动定位/预览、缩放/拉伸、圆角连接/尖角拓扑修复、拖动修剪、圆弧修剪/延伸，以及已提交约束草图的完整就地编辑。手工验收新增步骤见 docs/design/solid-edge-interaction-acceptance.md 第 7–10 项。

2026-10-25 follow-ups add single-click trim targets for lines/circles/arcs and direction-preserving circular arc endpoint extension. This paragraph records the earlier transform/offset slice. See [curve trim follow-up](task-P2-34-sketch-curve-trim.md) and [arc extension evidence](task-P2-34-sketch-curve-extension.md) for added behavior and tests.

资料：[Solid Edge Fundamentals ST5](https://support.industrysoftware.automation.siemens.com/training/se/en/ST5/pdf/mt01413-s-1050_en.pdf)、[CircularPatterns2d API](https://support.industrysoftware.automation.siemens.com/trainings/se/107/api/SolidEdgeFrameworkSupport~CircularPatterns2d_members.html)。

## 自动验证

测试：uv run pytest tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
结果：101 passed in 52.17s

Ruff：All checks passed；format：4 files already formatted。
basedpyright：0 errors, 0 warnings, 0 notes。
git diff --check：passed。

测试覆盖五种图元的移动/复制/偏移、身份语义、圆弧旋转/镜像/偏移方向、矩形类型转换、阵列坐标/身份/构造标记、无效/退化偏移和非法选择/参数拒绝、真实 Qt 选择/移动/复制/偏移/阵列和连续撤销，以及草稿变换经完成操作后只提交一个可重放草图命令。未运行全仓测试或 Solid Edge 桌面测试。
