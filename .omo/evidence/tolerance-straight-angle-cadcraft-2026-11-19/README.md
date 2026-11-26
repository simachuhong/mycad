# CADCraft 180° 三点参考角交换

MyCAD 输出下半圆 180° 三点参考角，偏差 +0.10°/-0.20°，对象 ID 为 `46` 重复 16 次。`source.dxf` 的 SHA-256 为 `4043d773627cc0386812d52378e910d89f6a58a2eb1d8f82c79ffb492c54f56a`。

CADCraft 0.20.1 CLI 使用 `--window=-20,-20,20,20 --export cadcraft.svg --save cadcraft.dxf` 打开、渲染并另存该文件。另存 DXF 已固定为 [测试样本](../../../tests/fixtures/dxf/cadcraft-straight-angle-resaved.dxf)，SHA-256 `49e07d7eb29a068e29f8363dfc9e611a30befdd1fe8b14a279a82ad7a5f567e8`；[SVG 转出的截图](cadcraft.png) SHA-256 为 `8b49684e87889a7b0b3167b3f19933a13a14ad0ffbdece2d6dbdba65b136adb7`。

MyCAD 重读保留原 ID、180°、下半圆位置和上下偏差；报告其为不关联几何的参考尺寸。截图可见下半圆及偏差，字形仍需结合目标 CAD、字体和标准人工评判。本记录只覆盖 CADCraft 的 CLI 打开、静态 SVG 与不修改另存，不代表 GUI 编辑或 AutoCAD 行为。

另对源文件句柄 `3C` 执行 `dimoverride {"handles":["3C"],"DIMTOL":1,"DIMTP":0.3,"DIMTM":0.4,"DIMTDEC":2}`，返回 `changed:1`。另存 [测试样本](../../../tests/fixtures/dxf/cadcraft-straight-angle-edited.dxf) SHA-256 `b6da7d69a4dab4b30abf95b6ca6de1f6eea7c5196822975318d91c5b986260b8`；MyCAD 读取到相同 ID、下半圆和 +0.30°/-0.40°，并提示原图形仅显示名义角度。CADCraft 的 [编辑后 SVG 截图](cadcraft-edited.png)确实未显示偏差；这是该 CLI 重生成路径的显示限制，不代表其他 CAD 或 GUI 编辑。
