# P2-31 — 标准导航与显式选择状态

日期：2026-10-24（初次记录）；2026-10-25 更新：**按确认范围完成 F 工程收口，人工体验待用户验收**。

最新范围、修复、297 项回归、8 组高 DPI 检查及原生桌面证据见 [F 收口记录](task-P2-F-closure.md)。以下保留初次实施历史；末尾的原未收口项已由更新说明取代。

## 已实现

- 增加前/后/左/右/上/下/等轴标准视图、正交/透视投影、全局 XYZ 坐标轴和 XY 网格。视角与投影保存在 UI 运行态，不改变文档或命令历史。
- 增加实体/面/边/顶点过滤、屏幕空间预选、点击选择、Ctrl 多选、包含/交叉框选、Esc 取消和 6 logical-pixel 拾取半径。几何修订、文档绑定或历史预览变化会清除过期身份。
- 选择身份同步到右侧面板；模型预选/选择的临时高亮分别为蓝色/琥珀色，选择动作不提交 Document 或 Bus 命令。

## 验证

定向 UI/协议/几何回归：

```text
uv run pytest tests/core/test_viewport_protocol.py tests/geom/test_viewport_snapshots.py tests/ui/test_viewport.py tests/ui/test_picking.py tests/ui/test_menus_toolbar.py -q
100 passed in 56.16s
uv run pytest tests/test_layering.py -q -> 6 passed
```

Ruff 检查、格式检查与 basedpyright 均通过（basedpyright 0 errors、0 warnings、0 notes）。在 Qt/xcb 1920×1080、DPR 1.0 的真实桌面完成顶视图、透视切换、悬停预选、点击选面和等轴视图截图。全窗口截图的视口中心像素均与单独 `grabFramebuffer()` 核对一致；状态报告记录 1 条命令前后文档修订和命令历史均不变，右栏显示所选面的实体及拓扑身份。

截图：

- [顶视图/正交/坐标轴与网格](phase2-foundation/p2-31-navigation-selection/standard-top-orthographic-axes-grid.png)
- [顶视图/透视/坐标轴与网格](phase2-foundation/p2-31-navigation-selection/standard-top-perspective-axes-grid.png)
- [面预选（全窗口）](phase2-foundation/p2-31-navigation-selection/face-hover-preselection.png) · [视口 framebuffer](phase2-foundation/p2-31-navigation-selection/viewport-face-hover-preselection.png)
- [面选择（全窗口）](phase2-foundation/p2-31-navigation-selection/face-click-selection.png) · [视口 framebuffer](phase2-foundation/p2-31-navigation-selection/viewport-face-click-selection.png)
- [等轴面选择](phase2-foundation/p2-31-navigation-selection/isometric-face-selection.png)
- [交互与像素核对报告](phase2-foundation/p2-31-navigation-selection/render-check.json)

## 原未收口原因（2026-10-24 历史）

手工二维绘图/编辑、建模操作预览与明确应用/确认依赖 P2-32+ 的几何操作闭环；当前只验证视图/选择状态不修改模型，不能据此宣称完整的操作预览与确认流程已完成。实机截图覆盖 100% 缩放；拾取半径回归在 0.5×/1×/2× 相机缩放下验证 5.9/6.1 logical-pixel 阈值。本轮未做 125%/150%/200% 实机或设备像素比模拟验证。因此 P2-31 仍部分完成。

## 2026-10-25 收口更新

用户已明确将真实二维/草图流程交 G 联验。现有八条命令的非遮挡参数、动态预览、继续选择/导航和确认边界已实现并纳入回归；导航、真实实体树、窄屏输入与高 DPI 证据见 [F 收口记录](task-P2-F-closure.md)。本项在 F 的三维工作台范围收口；二维/草图与最终人工体验结论仍待后续验收。
