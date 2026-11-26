# 基准宽字图形导出原始问题

`capture.py` 使用宽度因子 1.8 的基准 `B8` 生成不带画布快照的图形兼容 DXF；CADCraft 0.20.1 CLI 转换的 `cadcraft.png` 中基准文字只有空心轮廓，与 `canvas.png` 的填充文字不同。样例使用无快照的既有回退路径，仍保留该行为并在报告中说明结构化信息丢失。此图仅证明该样例，不代表其他 CAD。

SHA-256：

- `graphic.dxf`: `b15461b5aec13ac1f21b05ab05f89faf00a4ebe5da5418db32261ba1ecd4bac2`
- `canvas.png`: `ad0ddfb037828fac4538376dd1d28871d2adb6093fe100c0bd14c0a75d67150c`
- `cadcraft.svg`: `d71e1f6bfe0bd916d0922102e5ab4d386fdae505b636ecb1b3e29967b194a28e`
- `cadcraft.png`: `09a76062d56a908d960cd463ab39ba8cf84ad575c130b579d2c8b5aa76a87b38`
