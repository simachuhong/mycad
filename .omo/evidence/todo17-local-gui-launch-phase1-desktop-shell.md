# 本机 GUI 启动与真实入口缺陷修复（todo 17，用户请求"先在本机启动一下，便于我人工测试"）

## 症状（首屏截图实证）

`uv run mycad gui` 在本机 X11（DISPLAY=:1）能起进程、窗口存在（1269x760）、
日志无报错，但**客户区整片空白**：左侧命令库 / 中 GL 视口 / 右属性 Tab / 底栏 CLI+Chat
五区一个都没渲染；状态栏第一字段显示"未组合应用服务，无法打开"。

## 根因

`src/mycad/ui/entry.py::run_gui()` 只做 `build_app()` + `_ = new_document(services)`
（**丢弃 LoadedDocument**）+ `MainWindow()`（**不传 services**）+ `show()`。
既没注入 services 也没 `bind_document()` ⇒ MainWindow 走"无 services"降级分支：
中心是占位 QWidget（viewportHost）、三 dock 无内容、无 GL 视口、底栏 tabs 缺失，
`self._services is None` 使新建/打开/导出直接报"未组合应用服务"。
**该函数此前零测试覆盖**（tests/ 全树 grep `run_gui|ui.entry` 无命中）——
测试全部直接 `MainWindow(services=...)` 构造，故真实入口残缺而 CI 全绿。

## 修复

`src/mycad/ui/entry.py`（唯一改动源文件）：

    services = build_app()
    loaded = new_document(services)        # 必须在建窗之前：kernel reset 归 new_document 独占
    window = MainWindow(services=services)
    window.bind_document(loaded)
    window.show()

顺序不可换：`new_document` 独占 kernel reset，而视口要拿 kernel 端口。

## 回归测试（新增 tests/ui/test_entry.py，2 例）

- `test_run_gui_wires_services_and_a_fresh_document`：spy MainWindow 记录
  收到的 services 与 bind_document 的 LoadedDocument，断言 services 同一性 +
  文档已绑定 + 历史为空。
- `test_run_gui_builds_the_five_zones`：断言 viewport/command_palette/right_panel/
  bottom_tabs/cli_tab/plan_cards 全部存在 + 状态栏首字段为"空闲"。
- **篡改探针（红→绿闭环）**：把 entry.py 改回旧写法（`_ = new_document(...)` +
  `MainWindow()`）→ 2 例全 FAIL（`_services is None` / `viewport is None`）；
  还原 → 2 passed。测试确实能抓住原缺陷。
- 类型：`uv run basedpyright tests/ui/test_entry.py` 0 errors（spy 用
  `received_services` 自持引用，不读 `MainWindow._services`；`QApplication.exec`
  patch 用具名函数而非 lambda，避开 reportUnknownLambdaType）。

## 本机实证（DISPLAY=:1，X11 / mutter-x11-frames）

- 启动：`setsid nohup uv run mycad gui > /tmp/opencode/mycad-gui.log 2>&1 < /dev/null &`
  → 进程常驻、日志空（无报错）、窗口 1269x760。
- 截图（`/tmp/opencode/grab.py`：PySide6 QApplication + `primaryScreen().grabWindow(0)`
  → /tmp/opencode/screen.png，1920x1080）实证五区全部渲染：
  左"命令库"（feature/modify 分类树 + 搜索框）、中 GL 视口、右"属性"
  （结构/属性/选项/显示 四 Tab，结构树列出基准/草图/特征/实体）、底"控制台"
  （CLI / Chat 两 Tab）；状态栏五字段齐全且首字段 = **空闲**（旧版为
  "未组合应用服务，无法打开"）。
- 端到端几何实证（同屏内另起等价实例跑 F3 法兰三条命令）：
  `feature.cylinder` → `feature.hole` → `feature.hole_pattern`
  → snapshots=3 / mesh_visible=True / items=2；视口渲染出 OD80×8、⌀20 中心孔、
  4×⌀6 PCD50 的法兰（截图 /tmp/opencode/gui-flange.png）；
  右面板"特征"树同步列出 #0 圆柱体 / #1 孔 / #2 孔阵列；
  状态栏 → "当前：feature.hole_pattern（#2） | 选择 0 mm | 重建状态：重建中 | 已修改"。
- 清掉了旧壳留下的脏 QSettings（~/.config/MyCAD/MyCAD.conf 存着空壳布局记忆）。

## 已知残留（非本次缺陷，供人工 QA 时知悉）

1. **"重建状态：重建中"不复位**：bus 只在 undo/redo/replay 发 `geometry_rebuilt`，
   普通命令只发 `post_command`，于是重建态停在"重建中"。该行为被
   tests/ui/test_menus_toolbar.py:53 显式断言钉住，**不在本次改动范围**，
   留待人工确认后再决定是否调整语义。
2. 首屏那句"未组合应用服务，无法打开"的来源：全树无 setShortcut/QKeySequence，
   唯一写入点是 main_window.py:515（`_on_open_document` 的 services-None 分支），
   与本次修复前的降级分支一致——修复后已不可能再出现（状态栏实测为"空闲"）。

## 门禁（实测）

- `uv run pytest -q` → **884 passed**（134.91s；较 F 阶段 882 增 2 = 新增入口回归）
- `uv run ruff check .` → All checks passed；`ruff format --check .` → 188 files already formatted
- `uv run basedpyright` → 0 errors, 0 warnings, 0 notes
- 合规绿线：tests/test_scope_audit.py + test_layering.py + test_notice.py + test_adr_docs.py → 48 passed

## 交付状态

改动尚未提交（用户本轮未要求 commit）；工作树仅 2 个文件变更：
`src/mycad/ui/entry.py`（修复）、`tests/ui/test_entry.py`（新增）。
