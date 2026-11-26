# 旧式基准原生 DXF 的框尺寸对照

旧式 `B8` 基准使用 DejaVu Sans、字高 5.5 mm、宽度因子 1.8。修正前从画布测得的框约 20.4432 × 10.0722 mm，`before.dxf` 原生块约 22.2665 × 7.8571 mm。`capture.py` 使用当前代码在隔离 Xvfb 中取得画布快照，`after.dxf` 采用画布框尺寸和引线，文字基线按框与字高近似居中，保留 MyCAD 基准元数据。CADCraft 0.20.1 CLI 将两份文件转换为 SVG/PNG，并将新文件另存为 `resaved.dxf`；MyCAD 可从该另存文件恢复同一旧式基准身份、名称、位置和目标。另存文件也复制为定向回归夹具。

画布快照决定本样例的框和引线；原生 TEXT 在目标 CAD 可能替代字体或采用不同排版，导出报告保留该提示。样例不能证明 AutoCAD 行为，也不能替代真实桌面与标准专业验收。`before.dxf` 是修复前实际生成的对照，当前脚本仅生成修正后文件。

SHA-256：

- `before.dxf`: `acd9ecf62929a702bc8c7cf0288e18a8c17a743556655e101c641571c9a99d0b`
- `after.dxf`: `4018ab7ca532711adcc4d52d4decce32f421c9e4945742525000b59073532d57`
- `resaved.dxf`: `b5177d84efdcc2b708d3e512d254108a8f39d7a611bd76fcdb3f467f6174bfbd`
- `canvas.png`: `afe77aeb23fe0d13722ee3577575e875aaaaa50d66ebf1e74b9cfdf70cd54c6b`
- `before.svg`: `627e0bf29a6de032a2a282c1a902534bd9bb6c8e2534fb4068ba6b290e493b62`
- `after.svg`: `13605a8a4a5d912fb9994609742419e59f2abd173c30c7d2a8515bd140061340`
- `before.png`: `a15d457651c3aba227255bf921f1087d1700f878a09ab36f62db7e3abc1c6e0e`
- `after.png`: `8ff5383f972325405775f9473bcfb02e55fd62d76d1e81ec3afbcbb74c2a8363`
