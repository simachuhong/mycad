# 公差框图形导出：框边与字体替代

`capture.py` 在隔离 Xvfb 桌面使用实际 MyCAD 画布布局生成右侧引线样例 `graphic.dxf` 和 `canvas.png`。CADCraft 0.20.1 CLI `convert graphic.dxf cadcraft.svg` 后转成 `cadcraft.png`。在该样例中，引线与右框边接触；但 CADCraft 替代字体使数字越过框线，文字兼容缺陷尚未解决。此样例不能证明 AutoCAD 的显示或其他角度和字体均正常。

SHA-256：

- `graphic.dxf`: `59f067aed43cc01b10a0ea7103b5650b833f7a1951d576899b2f4b303fb4daff`
- `canvas.png`: `53927443dfa2a3c638a46adbf7c6b12d70043b668326ab068de3e7ac1be47ba6`
- `cadcraft.svg`: `1c3eefa1dd24184cb868e4fb5ee6a7f7b87461e884a2026a5f1abbc148901ae2`
- `cadcraft.png`: `961fb7468027e5a78580d345372ed35df96362f4c8194708df9e75ce3b6b0feb`
