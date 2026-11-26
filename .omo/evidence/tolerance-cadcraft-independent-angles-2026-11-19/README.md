# CADCraft 独立创建角度尺寸的导入验证

2026-11-19 使用 CADCraft CLI 0.20.1，从空白毫米图纸创建三点角度尺寸并设置上下偏差，未使用 MyCAD 文件或扩展数据。执行环境的 CLI 位于 `/tmp/mycad-cadcraft-validation/cadcraft-0.20.1-linux-x86_64/bin/cadcraft-cli`，配置目录为 `/tmp/mycad-cadcraft-validation/config`。

```bash
CADCRAFT_CONFIG_DIR=/tmp/mycad-cadcraft-validation/config cadcraft-cli run --metric \
  --cmd 'dimangular {"vertex":[0,0],"p1":[0,30],"p2":[30,0],"at":[-20,-20]}' \
  --cmd 'dimoverride {"handles":["{last}"],"DIMTOL":1,"DIMTP":0.1,"DIMTM":0.2,"DIMTDEC":2}' \
  --window=-40,-40,40,40 --export reflex.svg --save reflex.dxf

CADCRAFT_CONFIG_DIR=/tmp/mycad-cadcraft-validation/config cadcraft-cli run --metric \
  --cmd 'dimangular {"vertex":[0,0],"p1":[-10,0],"p2":[10,0],"at":[0,-15]}' \
  --cmd 'dimoverride {"handles":["{last}"],"DIMTOL":1,"DIMTP":0.1,"DIMTM":0.2,"DIMTDEC":2}' \
  --window=-20,-20,20,20 --export straight.svg --save straight.dxf
```

两个命令均返回尺寸句柄和一项已修改的覆盖值。SVG 分别经 `rsvg-convert` 生成 [270° 图像](reflex.png)及 [180° 图像](straight.png)。这两个图像显示名义角度但没有显示偏差，因此不能将其视为公差视觉互操作通过。

| 样本 | SHA-256 |
| --- | --- |
| [270° DXF](../../../tests/fixtures/dxf/cadcraft-independent-reflex.dxf) | `62c72e3c11b8ab701cad5b84682474c2ac378be25ff9580f62017cb2d5656ea1` |
| [180° DXF](../../../tests/fixtures/dxf/cadcraft-independent-straight.dxf) | `696406f359a3330b79af9171fcb886fb74fb4dd6200c51c5a6e4214bc43988a4` |
| 270° PNG | `ac8cddc5227d381a1f145b9e991c23e6a1a97f2dd6fd77d18608e87dbfd52bed` |
| 180° PNG | `f70f11da6c7f401dbe83098498bd4269e7d682dac253d9b6b993b7dd7f2c0d80` |

MyCAD 将其导入为不关联源几何的参考尺寸，恢复名义角和 +0.1°/-0.2°，并提示无法核对原生圆弧以及源图形未显示公差。`uv run --no-sync pytest tests/formats/test_dxf_detached_dimension.py::test_cadcraft_independent_angle_import -q`：2 passed。对该测试文件运行 Ruff 检查、格式检查和 basedpyright 均通过。

这是 CADCraft CLI 的有限样例，不证明 AutoCAD 的显示或编辑行为，也不代替 GB/ISO 专业复核和真实桌面人工验收。
