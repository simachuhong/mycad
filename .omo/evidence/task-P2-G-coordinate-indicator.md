# P2 G：坐标方向显示与极点拾取修复

日期：2026-10-25。触发：用户反馈坐标系只有一根纵线、显示过于简陋。

## 问题与修复

旧 GLAxisItem 固定轴长 50 mm，而空视口相机距离为 10；真实 XCB 复现端点越界、无线宽强调、无 XYZ 字母。未读取用户窗口，不能声称复现了用户当时的全部画面。

改为 Qt 鼠标穿透叠加层：左下常驻全局 XYZ 方向标，红/绿/蓝箭头和文字同时辨识方向，跟随真实 GL 相机旋转但不随模型缩放。正对轴时显示圆点/叉区分朝向。原菜单开关控制实际世界原点的附加标记 O (0,0,0)，不把角落方向标当作模型原点。原点标记超出安全区域或与角落指示器重叠时隐藏。明暗主题使用不同颜色；采用逻辑像素。

参考：[Autodesk UCSICON 官方说明](https://help.autodesk.com/cloudhelp/2022/ENU/AutoCAD-LT-MAC/files/GUID-EA2D8ACA-336A-4656-BFD3-43BC371C6171.htm)。本次不实现可编辑 UCS、视图立方体或 Solid Edge 原生坐标控件。

对照实际 GL 相机矩阵时发现另一处真实缺陷：`camera_basis` 在俯视/仰视附近更换 world-up，导致拾取及投影相对渲染旋转 90°、接近极点时不连续。改用与 pyqtgraph Euler 矩阵一致的解析 right/up 向量。标准视角本身保持原约定。

## 自动证据

- 新方向标测试先 11 FAIL（接口缺失），实现后 11 PASS。
- 投影/拾取与真实矩阵对照：先 4 FAIL/21 PASS，失败均在 top/bottom，覆盖正交及透视。
- 首轮相关回归 120 PASS/1 FAIL：旧拾取半径测试在投影退化为点的 BREP 边角上沿固定屏幕 Y 移动，可能沿邻边行进。改为已知盒体 +X 边中点垂直向外测量，仍分别断言 5.9 px 命中/6.1 px 不命中，没有扩大容差。
- 最终定向：`uv run pytest tests/ui/test_coordinate_indicator.py tests/ui/test_picking.py tests/ui/test_modeling_interaction.py tests/ui/test_p2_g_part_workflows.py -q`：**88 passed in 66.03s，exit 0**。包含三色实际绘制、近极点、世界投影/拾取、导航相关调用与建模流程。
- 首轮中的 viewport/navigation/menu/layering 其余测试已通过；最终没有重复无关全量。
- 修改的坐标组件、viewport、坐标和拾取测试 Ruff / format / basedpyright 均通过。
- 图像：`phase2-g-coordinate-indicator/isometric-light.png`、`top-light.png`、`front-dark.png`、`bottom-dark.png`。真实 XCB，等轴测浅色与正视深色已人工视觉核对（代理自检）。

## 边界

当前用户已打开的进程不会热加载源码，不强制关闭其窗口。截图和自动检查不代替用户人工验收。P2 G 主线仍继续，未标记整体完成。
