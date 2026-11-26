# 旧隐藏引线的 CADCraft 交换与布局检查

`generate.py` 生成两个含隐藏顶点的原生 DXF；以 CADCraft 0.20.1 CLI 另存为 `route-resaved.dxf` 和 `normal-resaved.dxf`。该版本保留 MyCAD 扩展数据，但丢弃 LEADER 的原生关联句柄。现仅在公差框和引线身份唯一、原生几何及其余证据一致时恢复原拓扑和约束，并报告原生关联缺失。样本的另存结果已加入定向回归夹具；重复框、重复引线、错误句柄、箭头和颜色修改会拒绝恢复约束。

`capture_actual.py` 使用当前 MyCAD 画布字体布局生成 `actual-source.dxf` 和 `actual-canvas.png`。在 CADCraft 的 SVG 导出路径中，`actual-cadcraft.png` 的原生 TOLERANCE 框底与引线端点存在可见间隙；SVG 中框围绕插入点上下排布，与本软件画布以插入点作为框左上角的布局不同。通过当前图形兼容转换生成 `actual-graphic.dxf` 后，`actual-graphic-cadcraft.png` 的这一底边连接可见。该样例不代表所有框侧、字体或 AutoCAD 表现。Autodesk 的 [DXF TOLERANCE 说明](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-DXF/files/GUID-ADFCED35-B312-4996-B4C1-61C53757B3FD.htm)给出插入点字段，但未规定各软件的实际字体度量与包围框；不能据此断言 AutoCAD 采用 CADCraft 的布局。

关键 SHA-256：

- `route-resaved.dxf`: `bf337f2ab053a319db41c9143e8257d6fab275eecb60224fc65d45509ca0bae4`
- `normal-resaved.dxf`: `bff0d68f6101ef253cd67dbd53d363ce58ce217699c0847aa1612cc0c5d9188c`
- `actual-source.dxf`: `4101f424990025701f3c796c81d41397dff688d54e7113f6212c01018f41a47b`
- `actual-canvas.png`: `29a59ec0379be99973cbad53755610c82a64c71d97f583ceb6fd7cede77eec22`
- `actual-cadcraft.png`: `1d83a3cc7b81baea218125fb6ce8ea3c4a1e28ccef395325685353f329ef64df`
- `actual-graphic-cadcraft.png`: `6fd3a9358b101d8b6adabae6a4706d9aa8fe220aafde08b240253671e90fb5a3`
