# CADCraft 短公差框引线验证

MyCAD 导出单行公差框，主引线顶点 `(0,0)` 和 `(1,0)`，箭头尺寸为 1 mm。`short.dxf` SHA-256 `69ee8a6c825e0f5c6a42407c521f15f892a73bb197438026a805408ec281ad30`。

CADCraft 0.20.1 CLI 使用 `--view extents --export short.svg --save cadcraft-resaved.dxf`，随后 `rsvg-convert` 渲染 `short.png`。图中可见公差框及左侧箭头；这是该程序 SVG 导出路径的单一样例，不证明 AutoCAD 或真实 GUI 外观。SVG SHA-256 `b802eba360fc1517c218b2eea284ddb59e25ec4298435529cc5e11cd2e2b23b01e1e388ded7076c68`；PNG SHA-256 `7e8ba0b1a66512ebcb37a70f41103da30021a4f412d7f0b89495b226075fa8ed`。

CADCraft 另存后的 DXF 保留 1 mm 箭头尺寸及引线顶点，但移除 LEADER 的原生关联句柄。MyCAD 依据唯一扩展身份恢复并提示；[测试样本](../../tests/fixtures/dxf/cadcraft-short-leader-resaved.dxf) SHA-256 `b720b7dc111295d2953ade6f5dec25e43a38d2190691ee2eb06b62e5310e0306`，定向测试 1 项通过。
