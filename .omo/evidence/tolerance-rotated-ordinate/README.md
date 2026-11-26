# 旋转坐标尺寸 CADCraft 交换验证

MyCAD 导出一个局部坐标轴旋转 90° 的 Y 坐标参考尺寸，原点 `(10,20)`、特征点 `(14,23)`、引线端点 `(18,28)`，名义值 −4，上下偏差 +0.1/−0.2。执行 CADCraft 0.20.1：

```text
cadcraft-cli convert source.dxf resaved.dxf
```

原始 DXF 的尺寸方向组 51 为 −90°。CADCraft 另存后的尺寸缺失该组码，MyCAD 读回时按原生 0° 轴得到名义值 3，并依据保留的 MyCAD 轴方向快照明确警告方向改变；公差字段仍为 +0.1/−0.2。此处采用外部原生语义，不能保证外部结果与原图相同。另存样本用于 `tests/fixtures/dxf/cadcraft-rotated-ordinate-resaved.dxf` 定向回归。

```text
8ccf5db991cf01ca7d40a9e5cfe80ddc7bcfeb68cc7b68a0b1c51cc597aeef75  source.dxf
96081d6a68c5b6a7da77f2b9803d5a5209dd1fb9281d27f0f5e9db3387fc98ae  resaved.dxf
```

本次仅验证命令行另存及 MyCAD 读取，未验证 CADCraft GUI 或 AutoCAD，也不构成标准复核。

另对 `source.dxf` 使用 `cadcraft-cli run source.dxf --view extents --export source.svg`，并以 `rsvg-convert` 生成 `source.png`。该 SVG 路径可见旋转后的负名义值、上下偏差和引线；采用 CADCraft 的轮廓字体及布局，不能据此认定与 MyCAD 画布或 AutoCAD 外观一致，也不能代替交互验收。

```text
161e5c9827bffe70144a5ace0061d04624f170298274e883b174e41772619ae7  source.svg
b294860873be4c9e30061e402b3fd231d6694e6cdb772eca0e9c10326795fa5f  source.png
```
