# 版本 25 自动引线 DXF 样例

`capture.py` 在 Xvfb/xcb 虚拟桌面中通过基准与公差框工具放置两个标注，截图并导出 `sample.dxf`。固定样例的输入 SHA-256 为 `99665e024e73365fa121f708f6ebd33b7f3f3826e70ed5bce91c520d35bd1333`。脚本模拟对话框确认且每次使用新 UUID，不是人工操作验收，重生成的文件哈希会不同。

使用本机 CADCraft 0.20.1 CLI 打开并另存该 DXF，保存到 `cadcraft-resaved.dxf`，同时生成 `cadcraft.svg`；其 SHA-256 分别为 `fd99c482f983d7adf685e052fbef0e339c0f4a8d96a5f4e94f101564670e15bd` 和 `9f5758c75eca57fd9a428f5dc1a1381f06032d7fe52e25890a29fac16b671ee7`。固定另存样本已复制到 `tests/fixtures/dxf/cadcraft-v25-autoroute-resaved.dxf`。MyCAD 重新导入后两种对象都保留算法版本 2 和自动约束；CADCraft 移除的原生引线关联通过唯一身份恢复并提示。

```bash
XDG_CONFIG_HOME=/tmp/mycad-tolerance-qa-config QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a -s '-screen 0 1600x1000x24' uv run python .omo/evidence/tolerance-v25-dxf/capture.py
CADCRAFT_CONFIG_DIR=/tmp/mycad-cadcraft-validation/config /tmp/mycad-cadcraft-validation/cadcraft-0.20.1-linux-x86_64/bin/cadcraft-cli run .omo/evidence/tolerance-v25-dxf/sample.dxf --window=-10,-10,100,30 --export .omo/evidence/tolerance-v25-dxf/cadcraft.svg --save .omo/evidence/tolerance-v25-dxf/cadcraft-resaved.dxf
```

仅证明当前样例在该软件的 CLI SVG 和另存路径中的表现；不代表 AutoCAD 外观、交互或 GB/ISO 专业验收。
