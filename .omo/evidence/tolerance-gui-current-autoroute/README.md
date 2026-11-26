# 当前自动引线画布及 CADCraft 交换自检

使用隔离 Xvfb、Qt xcb 和软件 OpenGL 运行 `capture.py`。脚本建立一条直线，通过机械式基准和公差框入口输入坐标，自动接受名称和公差框对话框，并导出当前 DXF。`canvas.png` 与 `dark-canvas.png` 分别显示明亮和暗色画布，基准框与公差框的引线、箭头和文字可见；此图形与历史捕获恰好一致，但当前导出的基准使用自动布线算法 4、持久框尺寸，公差框使用自动布线算法 2。

在 CADCraft 0.20.1 的隔离深色 GUI 打开同一 `sample.dxf` 并缩放范围，截图 `cadcraft-gui.png` 可见直线、两个框及引线、箭头；公差框箭头显示得明显更细小，字体和尺寸也有差异，不将外观判为完全一致。CADCraft CLI 另存为 `cadcraft-resaved.dxf`；MyCAD 再导入后两对象的完整结构与原 DXF 导入结果相等，基准及公差框的几何附着和自动布线标记保留。公差框原生引线关联缺失，按唯一身份恢复并报告。另存文件作为 `tests/fixtures/dxf/cadcraft-v27-autoroute-resaved.dxf` 进行定向测试。

- 明亮画布 SHA-256 `a5547489f6064bede6635a9d9f8c6db25cd10e4b5785e12f55796972a41c7263`
- 暗色画布 SHA-256 `370719c37b7db9046fff78e38fe3b6d4f78a463c229130456be13815d0531beb`
- CADCraft GUI SHA-256 `c6a1d1c927487a84aba09eaf41d9fdb9d7f856081bd9b691994c996f97efd7bd`
- 原始 DXF SHA-256 `4799db4da250015880533cca0c722dfadba609092f53ea4a80880f3ef5f3e19f`
- CADCraft 另存 DXF SHA-256 `08d7adce7eab621c8ab697097cb542328054d71ae33a2a726fa55176955064d6`

自动接受对话框和程序坐标输入不能证明真实鼠标体验、AutoCAD 对标或 GB/ISO 合规。GUI、Xvfb 进程已结束；字体由本环境提供，其他字体可能不同。
