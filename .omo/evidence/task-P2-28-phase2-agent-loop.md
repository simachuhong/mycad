# P2-28 — 背景颜色与视口可视性基线

日期：2026-10-24；状态：**P2-28 验收完成**。

## 已落地

背景改用 Qt 可正确解释的 `#EFF3F7`，网格与边线继续使用 GL 0～1 浮点颜色。
回归检查实际 widget.opts 中的 RGBA 转换结果，修复前为 `(0,0,0,1/255)`，
修复后为 `(239/255,243/255,247/255,1)`，不只比较常量字符串。

Qt/xcb 在 Intel HD Graphics 620、Mesa 25.2.8、OpenGL 4.6 上实际渲染空文档、法兰、薄板和圆柱；
framebuffer 背景像素均为 `(239,243,247,255)`，完整环境见 [render-check.json](phase2-foundation/render-check.json)。
相关测试通过；本批总体验证见 [verification.md](phase2-foundation/verification.md)。

## 视觉复核及剩余工作

[当前工作台截图](phase2-foundation/light-workspace.png) 显示背景已变亮，但实体背光面仍明显偏暗，
三角剖分边较杂，高亮在真实渲染中不够清晰；圆柱等长宽比例样本还暴露适应窗口取景不足。
因此不能据背景测试全绿宣称整体 UI 或 P2-28 可视性验收完成。
这些问题随 P2-29/30/31 的布局、光照/法线、BREP 边界、选择及相机规格继续处理，
当前代码保留现有渲染路线，不提前引入未经决策的新后端或独立着色框架。

原 v0.1 设计稿仍是未来目标；本次实际应用截图与设计稿分开保存，不混称设计稿已实现。

## 2026-10-24 光照增量复核

新增 `GLViewport` 共用的 `build_workbench_shader()`：使用世界空间法线与 `(0.35, -0.25, 0.90)` 顶光方向，片元阶段归一化光向量，采用 `0.45 + 0.55 × max(dot(normal, light), 0)` 的填充/漫反射。实体和现有选择覆盖层复用该 shader；实体/边线 GL 色保持不透明，琥珀色选择 alpha 仍为 `0.45`。新 shader 接口增加本地 pyqtgraph shader 类型 stub，没有新增运行时依赖。

真实桌面复核使用 Qt xcb、Intel HD Graphics 620、Mesa 25.2.8、OpenGL 4.6 Compatibility Profile，隔离 QSettings。截图和像素记录位于 [`p2-28-shader`](phase2-foundation/p2-28-shader/)；法兰顶面采样坐标 `(240,160)` 为 `(174,181,193,255)`，背景为 `(239,243,247,255)`。空文档、法兰、薄板、圆柱均重新捕获，shader 在真实 OpenGL 上编译并渲染。

验证：shader 回归先因仍使用 pyqtgraph 背光 shader 而失败；世界/相机法线空间错配修复的回归也先失败再通过。`uv run pytest tests/ui/test_viewport.py -q` → 13 passed；scoped Ruff 与 basedpyright 检查通过（0 errors/warnings/notes）。

## 后续任务联合复核

P2-30 加入 BREP 边界显示并移除默认实体上的剖分对角线；P2-31 修复相机射线映射，完成真实鼠标预选/面选择、琥珀高亮和右栏身份同步。最新同桌面 xcb 实测截图和状态报告见 [P2-30 渲染模式矩阵](phase2-foundation/p2-30-render-modes/render-check.json) 与 [P2-31 导航/选择矩阵](phase2-foundation/p2-31-navigation-selection/render-check.json)。因此 P2-28 原有的选择可见性和工程边界依赖缺口已关闭。

明亮工作台的完整信息架构仍由 P2-29 跟踪；该项本身已完成的背景颜色、顶面照明与视口选择可见性基线不依赖未实现的二维草图操作。

## 2026-10-25 F 联合回归

保留本项已确认的几何/渲染/性能结论。本轮补齐暗色 GL 背景与边线、候选预览配色，并修复多 GL 上下文共用 shader 编译对象的问题；完整 UI 及关联回归 297 项通过，原生 Intel/Mesa 桌面与隔离高 DPI 矩阵记录见 [F 收口记录](task-P2-F-closure.md)。没有重复运行已确认的 P2-09 性能基准。
