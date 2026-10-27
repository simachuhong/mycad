# P2-30 — BREP 工程边界与分层渲染

日期：2026-10-24；状态：**完成**。

## 实现

- 在中立 `ViewportData` 中增加带 `BodyId` / `TopologyId` 的边界折线；几何适配层按修订缓存采样，模型回放或文档替换后旧运行时身份失效。`Tessellation` 和 `.mc.json` schema 未改。
- 提供 `shaded`、`shaded-edges`、`engineering-wireframe`、`mesh-diagnostic` 四种独立显示模式。常规显示只画 BREP 边界，三角剖分线仅在诊断模式绘制；顶面光照与线条深度规则沿用 P2-28 的视口 shader。
- 关闭周期曲面的单面接缝线，保留圆形端缘、孔口/孔壁和圆角轮廓。选择覆盖仅在临时渲染几何上施加轻微相机方向偏移，避免共面深度冲突。

## 验证

定向回归：

```text
uv run pytest tests/core/test_viewport_protocol.py tests/geom/test_viewport_snapshots.py tests/ui/test_viewport.py tests/ui/test_picking.py tests/ui/test_menus_toolbar.py -q
100 passed in 56.16s
uv run pytest tests/test_layering.py -q -> 6 passed
```

Ruff 检查、格式检查与 basedpyright 均通过（basedpyright 0 errors、0 warnings、0 notes）。实际 Qt/xcb 截图矩阵包含平板、曲面、带孔、圆角、薄板五类模型与四种模式，共 20 张 1920×1080 / DPR 1.0 截图。平面 `shaded-edges` 没有内部三角对角线；带孔和圆角样本的工程边界可见。完整截图和计数见 [`p2-30-render-modes`](phase2-foundation/p2-30-render-modes/)；[渲染矩阵报告](phase2-foundation/p2-30-render-modes/render-check.json)。

按 P2-09 相同的场景刷新范围测量 30 个样本：

| 特征数 | 场景刷新 P95 | P2-09 基线 P95 | 预算 | 结果 |
|---:|---:|---:|---:|---|
| 10 | 14.44 ms | 14.59 ms | 20 ms | 通过 |
| 50 | 30.32 ms | 51.37 ms | 65 ms | 通过 |
| 100 | 60.27 ms | 99.02 ms | 125 ms | 通过 |

原始数据见 [benchmark.json](phase2-foundation/p2-30-render-modes/benchmark.json)。冷缓存网格构建仍需约 0.66 / 1.71 / 2.33 秒（10 / 50 / 100 特征）；同修订热缓存访问 P95 小于 0.024 ms。性能数字只表示视口数据/场景刷新，不包括 OCCT 命令执行或真实屏幕帧率。

## 2026-10-25 F 联合回归

保留本项已确认的几何/渲染/性能结论。本轮补齐暗色 GL 背景与边线、候选预览配色，并修复多 GL 上下文共用 shader 编译对象的问题；完整 UI 及关联回归 297 项通过，原生 Intel/Mesa 桌面与隔离高 DPI 矩阵记录见 [F 收口记录](task-P2-F-closure.md)。没有重复运行已确认的 P2-09 性能基准。
