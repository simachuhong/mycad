# Todo 19 — GUI 运行时打磨（默认窗口尺寸 + CLI 动词表摸底）

## 症状
用户删掉陈旧 `~/.config/MyCAD/MyCAD.conf` 后首次启动，窗口只有 1045x735（本次实测
frame 795x735）；`main_window.py` 全文没有任何 `resize()`，窗口尺寸完全由 QSettings 存档
或 Qt 默认值决定 —— 新用户首次启动得到一扇挤的小窗。

## 修复
`src/mycad/ui/main_window.py::__init__` 增加一行 `self.resize(1400, 900)`，
位置在 `restore_window_state()` **之前**（有存档布局时存档仍然胜出；顺序约束已写进注释）。
实测真实 X11（1920x1080）：client 1400x900 / frame 1428x966。

## 回归测试
`tests/ui/test_menus_toolbar.py::test_window_requests_the_default_size`：
用 monkeypatch spy 捕获 `MainWindow.resize` 的**请求值**并断言 `(1400, 900) in requested`。
为什么断言请求值而非实际像素：离屏（offscreen）平台的虚拟屏只有 800x800，
Qt 会把顶层窗口夹到 798x774，任何像素级断言都无法在 CI 成立。
**篡改探针（红→绿）**：删掉 `self.resize(1400, 900)` → 该测试 FAIL（`assert (1400, 900) in []`）；
还原 → 13 passed。

## CLI 动词表摸底（用户 `feature.box` 报错 → 根因）
- 现象：在 GUI 底栏 CLI 页输入 `feature.box` → `unknown command verb 'feature.box'`。
- 根因：CLI 动词是**短名**，与命令 id（`feature.*` / `modify.*`）不是一回事。
  动词表定义在 `src/mycad/builtin_commands/specs.py` 的 `CliSyntax(verb_aliases=...)`：
  `box` / `cylinder` / `extrude` / `revolve` / `hole` / `hole-pattern` / `fillet` / `cut`。
  解析入口 `src/mycad/commands/grammar.py::parse_line` → `registry.resolve_verb`，
  未命中抛 `UnknownCommandError`（带最近别名建议）。
- 结论：非缺陷，是动词/id 混用；已把三行正确命令交付用户。
- 待用户决定（未实现）：把 `mycad commands` 的动词清单做成 GUI 内可查表。

## 法兰测试文件
- 源文件在仓库内：`examples/flange_script.txt`（ASCII CLI 脚本）与 `examples/flange_plan.json`
  （等价 JSON 计划）——几何完全由命令参数驱动，没有 Python 建模脚本。
- 产物（仓库根，已被 .gitignore 忽略）：`flange.mc.json` 1.6KB / `flange.step` 24KB /
  `flange.stl` 148KB；理论体积 36794.33 mm³；历史 confirmed_by=cli-local。
- 参数：OD φ80x8 厚、中心孔 φ20 通、4xφ6 通孔 PCD50（start_angle_deg=0 对齐全局 +X）。
- GUI 侧入口：底栏 CLI 页逐行敲三行；或 文件→打开 选 `flange.mc.json`
  （GUI 没有"载入 .txt 脚本"入口 —— 脚本/JSON 计划只走 headless CLI，属已知功能缺口）。

## 本机实证（DISPLAY=:1，X11）
- live 实例：`setsid nohup uv run mycad gui > /tmp/opencode/mycad-gui.log 2>&1 < /dev/null &`
  → uv pid 140049 / python 140053；X 窗口 `0x600500 "MyCAD" 1428x966+246+73`；日志空。
- 截图工具：`/tmp/opencode/raise_grab.py <wid_hex> <out>`（ctypes XRaiseWindow 抬窗 +
  PySide6 `primaryScreen().grabWindow(0)` 整屏抓取）。
  注意：mutter 下 XResizeWindow/XMoveWindow 对 frame 窗口无效，改用代码内 `self.resize()` 才生效。
- 截图 `/tmp/opencode/screen_gui2.png` 实测：菜单 7 项 + 工具栏 12 按钮 + 左「命令库」
  （feature 树展开）+ 中 GL 视口 + 右「属性」四 Tab + 底「控制台」CLI/Chat + 状态栏
  「空闲 | 选择 0 mm | 重建状态：就绪 | 未修改」。

## 门禁
`ruff check` / `ruff format --check` / `basedpyright`（0 errors）/ `pytest tests/ui` 13+74 passed；
全量 pytest 见 ledger 同批记录。
