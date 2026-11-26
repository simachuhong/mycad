# 公差框填充字形跨软件样例

`capture.py` 使用隔离 Xvfb 下的 MyCAD 实际画布生成图形兼容 DXF：框格尺寸和已整形字形均由画布字体计算；数字作为填充轮廓输出。以 CADCraft 0.20.1 CLI 转为 SVG，再生成 PNG。相较上一例字体替代造成越框的结果，此样例中的数字位于框内、数字内孔可见，引线与右框边连接。该证据仅覆盖所示单行默认样例，不证明 AutoCAD、其他字体或所有复杂字形的表现。

SHA-256：

- `graphic.dxf`: `98480c42ccae29d8132cd82c6915e62d622c6aab49c8c925b46af2d9b32afda6`
- `canvas.png`: `53927443dfa2a3c638a46adbf7c6b12d70043b668326ab068de3e7ac1be47ba6`
- `cadcraft.svg`: `3014c753f14d8afc805bd78d2434821dd0300f18b33f600ab59827fb18b44cc6`
- `cadcraft.png`: `992e289a7cecfb3ec68ac2973c41741fce7ed60d0ca2b8fcbdbfb1be948d7131`
