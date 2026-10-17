# Evidence — phase1-desktop-shell todo 4 (ui 骨架 + `mycad gui` + offscreen 冒烟)

分支 `phase1-desktop-shell`；commit `feat(ui): five-zone main window shell and 'mycad gui' entry point`。

## 交付
- `src/mycad/ui/__init__.py`：包 docstring 声明分层契约（ui 禁 import mycad.geom）。
- `src/mycad/ui/main_window.py`：`MainWindow(QMainWindow)` 五区容器 —— 中央 `viewportHost` 占位、
  `leftPanelDock`/`rightPanelDock`/`bottomPanelDock` 三 dock（Qt 默认 features 已含 Floatable|Closable，
  测试断言锁位）、`mainToolBar`（movable+floatable+四边）、常驻 `QStatusBar`。
- `src/mycad/ui/entry.py`：`run_gui()` = QApplication + build_app() + new_document()（kernel.reset 独占于
  mycad.app）+ 窗 show + 事件循环。
- `src/mycad/cli/__main__.py`：`gui` 子命令（懒 import mycad.ui.entry，cli 保持 Qt-free）+ `--help`/`-h`
  直接输出 HELP_TEXT（此前 `--help` 落入 unknown subcommand；验收面文字 `mycad --help` 现可执行）。
- `src/mycad/cli/session.py`：HELP_TEXT 增 gui 行。`tests/cli/test_repl.py`：帮助断言增 `"  gui"`。
- `tests/ui/conftest.py`：`os.environ.setdefault("QT_QPA_PLATFORM","offscreen")`（ini 不能设 env、拒引
  pytest-env；setdefault 保 Windows native 覆写缝，todo 9 依赖）。qapp 由 pytest-qt 提供。
- `tests/ui/test_shell_smoke.py`：3 测试——五区字面量 objectName/statusBar/dock features 断言；
  GL 能力探针（QOffscreenSurface create+isValid → QOpenGLContext.create+makeCurrent 成功断言，
  Wave 1 即暴露三平台 CI GL 现实）；QTimer 单触发 `qapp.exec()==0` 干净退出。

## 门与探针
- `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui -q` → 3 passed。
- scoped 总门 `pytest tests/test_layering.py tests/test_scope_audit.py tests/test_ci_workflow.py
  tests/test_notice.py tests/ui tests/core/test_viewport_protocol.py tests/cli -q` → **132 passed**。
- `uv run mycad --help` 含 gui 行（实测 grep=1）。
- basedpyright `src/mycad/ui tests/ui src/mycad/cli … tests/test_layering.py` → 0e0w0n；ruff
  check/format 全绿；零 type:ignore。
- 修复的正路（layering 回归根因）：todo 1 的 `_is_forbidden_in` ui 分支曾把「非 numpy 判禁」写成
  整函数替代，本次实测 ui 引 PySide6 连 `__future__` 都报红——已正形（ui＝numpy 放行+build123d/OCP
  维持禁，Qt 中立归 scope_audit），泛化回归由 src/mycad/ui 真出现而暴露。
- 红绿探针（QA 场景「五区缺一 objectName 断言红」）：tamper `"leftPanelDock"→"leftPanelDockX"` →
  `test_shell_builds_the_five_zones` 1 failed → 还原 → 3 passed。
  **探针教训（已入测试设计）**：断言两侧同源常量使改名自洽（第一轮探针假绿）；objectName 是全
  阶段 1 绑定的身份契约，测试改锁字面量，常量漂移不再漏网。

## 诚实的计划偏差
1. **gui 本体在 `mycad/ui/entry.py` 而非 `cli/__main__.py` 内联**：scope_audit 的
   PySide6/shiboken6 carve-out 只认 `src/mycad/ui/` 前缀，cli 内联 import PySide6 被
   `test_no_forbidden_imports` 精确拦下（tamper 实证违规列表 `src/mycad/cli/__main__.py:81:PySide6`）。
   CLI 分支保持 Qt-free 是 guard 推出的正确形态。
2. **GL 探针为计划字面量的超集**：除 `QOpenGLContext.create()` 外额外断言 `isValid()` 与
   `makeCurrent(surface)`——更强，不算削弱。
3. **类型路径修正**：PySide6 6.12 wheel 自带全套 .pyi（QtWidgets.pyi 等，实测 ls），plan todo 9 的
   typings/pyqtgraph·PyOpenGL 手写策略仅覆盖该两者；另实证 stubs 不支持 property-kwargs 构造
   （`QWidget(objectName=...)` 报 reportCallIssue）→ 统一 `setObjectName()` 调用式。
4. **`QDockWidget.features()` 返回 Flags**（PySide6 stubs 语义），探针用 flags 位与而非 int() 转换。
5. test_repl.py 备注注释一iomni先加后撤（hook 优先级 4 判定非必要，断言自解释）。

## Must-NOT 复核
- 零面板内容（todo 5-8 产物）；零 pyqtgraph import；core/geom 完全未动（git status 变更面仅
  ui/、cli、tests）；gui 路径无 daemon/fork。
