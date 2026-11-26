# 形位公差界面截图自检

使用 Xvfb、Qt xcb 和软件 OpenGL 启动当前工作区的 MyCAD，创建一条直线，通过 `AMDATUMID` / `AMFCFRAME` 对应工具入口和坐标输入在其上放置基准与公差框，分别捕获明亮和暗色界面。截图检查工具栏图标和标签、画布中的框、引线及箭头的基本可见性。

- `window.png` / `canvas.png`：明亮界面，SHA-256 分别为 `aa7263aeb81fcb0a6e5763e33478bf514fd96b4d1c1bae0aada45114c811f7fe`、`a5547489f6064bede6635a9d9f8c6db25cd10e4b5785e12f55796972a41c7263`。
- `dark-window.png` / `dark-canvas.png`：暗色界面，SHA-256 分别为 `35d619ded789f16226ff935b23ddaee632731c1bee759b1c5554aecf40d2f411`、`370719c37b7db9046fff78e38fe3b6d4f78a463c229130456be13815d0531beb`。

复现：

```bash
XDG_CONFIG_HOME=/tmp/mycad-tolerance-qa-config QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a -s '-screen 0 1600x1000x24' uv run python .omo/evidence/tolerance-gui-selfcheck-current/capture.py
```

脚本用固定名称和自动接受的公差对话框避免阻塞，未检查输入对话框、真实用户鼠标习惯或 GB/ISO 的符号规则；截图也不构成与 AutoCAD 的对照。脚本在隔离配置和虚拟显示环境中运行，结束时直接退出以避免未保存图纸的关闭确认。

## CADCraft 交换样例

上面的脚本同时生成 `sample.dxf`，使用 CADCraft 0.20.1 CLI 打开、渲染和另存：

```bash
CADCRAFT_CONFIG_DIR=/tmp/mycad-cadcraft-validation/config /tmp/mycad-cadcraft-validation/cadcraft-0.20.1-linux-x86_64/bin/cadcraft-cli run .omo/evidence/tolerance-gui-selfcheck-current/sample.dxf --window=-10,-10,100,30 --export .omo/evidence/tolerance-gui-selfcheck-current/cadcraft.svg --save .omo/evidence/tolerance-gui-selfcheck-current/cadcraft-resaved.dxf
rsvg-convert -o .omo/evidence/tolerance-gui-selfcheck-current/cadcraft.png .omo/evidence/tolerance-gui-selfcheck-current/cadcraft.svg
```

该次输入、另存 DXF、SVG、PNG 的 SHA-256 分别为 `7811bb83d6dee8e3b9933e9cd8a4c706523e1857909e7766fd62203d974ff6c5`、`3955eaf5d378d7adf685e052fbef0e339c0f4a8d96a5f4e94f101564670e15bd`、`9f5758c75eca57fd9a428f5dc1a1381f06032d7fe52e25890a29fac16b671ee7`、`6696827a64f50fd47cb2dc12e5d57dbef837b1c7b4320113631c41f7c7b24ac1`。脚本每次生成新 UUID，重新生成的 DXF 字节和哈希会不同；固定另存样本位于 `tests/fixtures/dxf/cadcraft-v24-autoroute-resaved.dxf`。

CADCraft SVG 中可见直线、基准框、公差框和各自引线与箭头；文本字体、两种箭头比例与 MyCAD 画布外观并不完全一致。MyCAD 从另存文件恢复了两个对象及其自动法向、自动布线、防穿越和目标跟踪标记；公差框原生关联句柄缺失，通过唯一扩展身份恢复并给出提示。该样例不代表 AutoCAD 或其他软件的行为，也不代表 GB/ISO 专业验收。
