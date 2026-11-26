# CADCraft 两线反角 DXF 交换

MyCAD 输出 `mycad-reflex.dxf`：二维两线参考角 270°，上偏差 +0.10°、下偏差 -0.20°，对象 ID 为 `45` 重复 16 次。SHA-256：`1ae4329f27911b167c6886ee6cae9dc98e1024853c4458dbae419e39b71a3327`。

CADCraft 0.20.1 CLI 打开该文件，使用 `--window=-40,-40,40,40 --export cadcraft.svg --save cadcraft-resaved.dxf` 导出 SVG 并另存 DXF；`rsvg-convert` 转出 [PNG](cadcraft.png)。另存 DXF 的 SHA-256 为 `b9e9f73e8f5d302ba8fe0244bad7e3854a5bc5fe0af432d43e1493b26576bce4`，测试样本为 [cadcraft-two-line-reflex-resaved.dxf](../../../tests/fixtures/dxf/cadcraft-two-line-reflex-resaved.dxf)。SVG 和 PNG 的 SHA-256 分别为 `b6ac79216cccd0bfdf95b77cf319444bf8f825a947dfa54a6a1586cc602e6f8e` 和 `81f4098f379352e90f7170994dc47b5ae861421b162464f00870ea2aa5ee9dce`。

MyCAD 重新读取该 DXF 后保留对象 ID、270°、公差方式和 +0.10°/-0.20° 偏差；报告该参考尺寸不关联几何，原两线端点位置不保留。CADCraft SVG 图中可见 270° 弧线，但偏差文字挤在一起、靠近圆弧，外观不能判为通过。该结果仅覆盖 CADCraft 该版本的 CLI 打开、SVG 导出和不修改另存；不证明 GUI 编辑、AutoCAD 显示或标准合规。

修正图形块留白后，同一数据重新输出为 `mycad-reflex-clearance.dxf`（SHA-256 `5cf7f3254eb7421604eba5846e43a04d2885a8c5fabe51de7536ac2ea60a7e85`），相同 CADCraft 命令生成 [新截图](cadcraft-clearance.png) 和 `cadcraft-clearance.dxf`（SHA-256 `45144a711acb5ec81a52e9b82f5d8cad95e02f60aff49526bd642d64aa32cad6`）。截图中尺寸弧线不再穿过文字区域；留白偏大，偏差文字仍较拥挤，不能以此判定外观通过。另存后 MyCAD 仍读回 270° 和 +0.10°/-0.20°。这只验证该样例的 CLI SVG 路径；其他字体及 CAD 可能重新生成尺寸图形。

进一步按上下偏差分行估算避让边界后，同一数据输出为 `mycad-reflex-tight.dxf`（SHA-256 `00bdf3750c45cb2815649ce5d2d91b267737953c445ceb60b3fbf75c1f634143`），CADCraft 输出 [截图](cadcraft-tight.png) 及另存 DXF（SHA-256 `0c27b41b8a51aba0603677e9894241aa759b62cf1af62da0318af196cac81fa0`）。尺寸弧线缺口由约 30.8° 缩小至约 24.8°；截图未见弧线穿过文字，另存后对象 ID、270° 和上下偏差保持。该路径的偏差文字仍较拥挤，不代表其他软件或人工视觉验收通过。

使用 CADCraft CLI 对 `mycad-reflex-tight.dxf` 的句柄 `3C` 执行 `dimoverride {"handles":["3C"],"DIMTOL":1,"DIMTP":0.3,"DIMTM":0.4,"DIMTDEC":2}`，返回 `changed:1`，另存 [DXF](../../../tests/fixtures/dxf/cadcraft-two-line-reflex-edited.dxf)（SHA-256 `d52ce8fd7911b34378818ed247d592039270e21b351d292679073d78305f6b64`）。MyCAD 保留 ID 和 270°，读回 +0.30°/-0.40°。但 CADCraft 重新生成的尺寸块 MTEXT 只有 `270,00°`，[SVG 截图](cadcraft-edited.png)中也看不到偏差；MyCAD 对能识别的此类“只有名义角度”的图形会提示原图未显示公差。该检测不能证明其他格式图形的显示完整，且此结果不是 GUI 编辑或 AutoCAD 证据。
