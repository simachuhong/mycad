# Todo 18: 工具栏按钮落地 + 底栏控制台可见性（人工 QA 反馈闭环）

触发: 用户在本机 GUI 上实测后反馈「没看到工具栏」（截图里菜单栏下方为空白条），
同时底栏「控制台」（CLI/Chat）在该实例里不可见。

## 症状

- 菜单栏（文件 编辑 视图 特征 工具 智能体 帮助）正常，**其下方本应是 Toolbar 的位置是空白**。
- 该实例里底栏「控制台」不可见（状态栏直接贴在视口下方）。

## 根因 1 — Toolbar 从未装按钮（代码级确认）

`src/mycad/ui/main_window.py` 构造了 `QToolBar("main")`（对象名 mainToolBar，可消隐/换边/锁定），
但**全文没有任何一处把 action 加进 toolbar**：所有 `addAction` 调用都指向 `self.menu_*`。
探针（offscreen 实例）输出：`toolbar actions : []`、`toolbar visible : True h=17`
⇒ 只渲染成 17px 空条 = 用户看到的「空白」。UI 初稿 §实现注记原本写「高频动作按钮后置，
构造时暂无 action」——即阶段 1 有意推迟，本 todo 补齐。

## 根因 2 — 底栏控制台缺失 = 陈旧 QSettings 布局 blob

- 探针（fresh 配置目录）：`bottom dock vis: True h=282`、`bottom tabs: ['CLI','Chat']`
  ⇒ 代码路径正常，五区都会渲染。
- 探针（带用户真实配置副本）：dock 显隐被 state blob 带偏（左栏被藏起）。
- 该实例的配置由**修复前的空壳会话**（services 缺失 → 底栏当时没有 widget）落盘，
  `saveState` 把它记成隐藏；下次启动 `restoreState` 就把底栏藏了。
  ⇒ 处置：清掉陈旧配置后重启（用户可见效果恢复），不改动 restore 语义
  （QSettings 布局往返是 tests/ui/test_menus_toolbar.py 钉住的行为）。

## 修复（src/mycad/ui/main_window.py）

1. 新增 `TOOLBAR_MODELING_COMMANDS` 常量（UI 初稿 §4.2「建模高频」组）：
   拉伸→feature.extrude、旋转→feature.revolve、孔→feature.hole、圆角→modify.fillet。
2. 新增 `MainWindow._populate_toolbar()`（在 services 分支之后、`restore_window_state()` 之前调用）：
   - 菜单类按钮**复用同一批 QAction 对象**（新建/打开/保存/撤销/重做/适应窗口/着色·线框/
     查看待确认计划）⇒ 菜单与工具栏共用一份状态，勾选/启用不分叉；
   - 建模按钮为新 QAction，走左栏命令库**同一条起草路径**（`_on_palette_command`：
     草稿 → 确认 → 执行），没有 services 时禁用；
   - 首期无图标资源 ⇒ `setToolButtonStyle(ToolButtonTextOnly)` 落成文字按钮；
   - 合计 **12 个按钮**，落在 UI 初稿 §4.2「约 12–17 个」的区间内。
3. `MainWindow._on_toolbar_modeling(command_id, _checked=False)`：PySide6 的
   `triggered(bool)` 在 partial 绑定下可能不传 bool，故给默认值（首版写成必填参数
   → 实测 TypeError + teardown 报错，已修正）。

## 回归测试（tests/ui/test_menus_toolbar.py 新增 3 例）

- `test_toolbar_carries_the_high_frequency_actions`：按钮文本序列 == 12 项预期；
  且 `actions[0] is win.act_new`、`actions[5] is win.act_fit_view`、
  `actions[6] is win.act_shaded_wireframe`（同一 QAction 对象，状态不分叉）。
- `test_toolbar_modeling_button_starts_a_plan_draft`：点「拉伸」⇒ 状态栏出现「草稿：feature.extrude」。
- `test_toolbar_modeling_buttons_disabled_without_services`：无 services 时 4 个建模按钮禁用。

## 文档（有意变更）

`docs/UI设计初稿.md` §实现注记：把「高频动作按钮后置，构造时暂无 action」改为已落地 12 个
文字按钮的现状，并写明 §4.2 的选择/旋转观察/平移/窗口缩放由 GL 视口鼠标手势承担、
确认执行/取消计划在 Chat 计划卡片内完成。按基线流程重生成
`tests/fixtures/baseline_doc_sha256.json`（`scripts/gen_baseline_hashes.py`）。

## 本机实证（DISPLAY=:1，X11）

- 清陈旧配置 `~/.config/MyCAD/MyCAD.conf` → 重启 `uv run mycad gui`（pid 136585/136589，日志空）。
- 截图 `/tmp/opencode/screen3.png`（1920x1080）逐项核对：
  **工具栏 12 个文字按钮全部可见**（新建 打开 保存 撤销 重做 适应窗口 着色/线框 查看待确认计划
  拉伸 旋转 孔 圆角）；五区齐全：左「命令库」（搜索框 + feature/modify 树）、中 GL 视口、
  右「属性」（结构/属性/选项/显示 四 Tab）、底「控制台」（CLI / Chat 两 Tab）；
  状态栏「空闲 | 选择 0 mm | 重建状态：就绪 | 未修改」。

## 门禁（实测）

`ruff check .` All checks passed；`ruff format --check .` 188 files already formatted；
`uv run basedpyright` 0 errors / 0 warnings / 0 notes；`uv run pytest -q` **887 passed (139.42s)**
（todo17 的 884 + 本 todo 的 3）。

## 已知残留

- 工具栏尚无图标资源（纯文字按钮）；§4.2 的视图手势类按钮与「确认执行/取消计划」未上工具栏。
- 「重建状态：重建中」不复位是既有行为（tests/ui/test_menus_toolbar.py:53 钉住），本次未动。
