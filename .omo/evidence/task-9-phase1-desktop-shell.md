# 证据：task 9 phase1-desktop-shell（视口渲染 pyqtgraph.opengl）

- 提交：`feat(ui): pyqtgraph mesh viewport with shading/wireframe and fit`
- 变更面：`src/mycad/ui/viewport.py`（新，GLViewport + REFRESH_SIGNALS + unique_edges）、
  `src/mycad/ui/main_window.py`（中央 viewportHost=GLViewport、视图菜单着色/线框+适应窗口、
  rebuild_hook、bind_document 订阅、closeEvent dispose）、`typings/pyqtgraph/opengl/__init__.pyi`（最小手写
  stub，覆盖 GLViewWidget/GLMeshItem/GLLinePlotItem/MeshData 所用 API）、
  `pyrightconfig.json`（stubPath=typings）、`pyproject.toml`（stubPath 理由注记 + typings 加
  ruff extend-exclude 的 N802/N803 第三方 camelCase 镜像注记）、`tests/test_scope_audit.py`
  （numpy 允许面加宽至 src/mycad/ui/：`BACKEND_ALLOWED_PREFIXES`，build123d/OCP 仍仅 geom/）、
  `tests/ui/test_viewport.py`（新，8 测试）。

## 继承审计与第一派发
- 前两派发 6 连败全是基础设施（ark 配额烧尽×2 / kimi 连接失×2 / minimax 529×2），
  磁盘遗留 258 行 viewport.py 草稿 + typings 桩。被采纳并收尾；偏差修两处：
  ①派发的 SignalCallback 语义（单 payload 映射）在 partial(name, payload) 下合法；
  ②遗留草稿更新/重建收敛 `_schedule_refresh` QTimer.singleShot(0) 与计划 C3 一致。

## API 事实（实测）
- offscreen 下 GLViewWidget 可构造、addItem/removeItem/setCameraPosition/opts 读改全免 GL 上下文；
  `items` 列表线性有序，测试以 items 数==2（mesh+edges）断言「仅最终快照」。
- `setCameraPosition(pos=...)` 即设置 `opts["center"]`（GLViewWidget.py 源码逐行核对）。
- 内核快照网格以原点居中（bbox z∈[-4,4]），断言以实测为准。
- pytest-qt 无自动 QApplication：viewport 窗口级测试显式=qapp 签名。

## 平台兜底阶梯实测
- Linux 本地 offscreen：GL 上下文不可用 → 逐项断言全部可跑，paint 异常被 pyqtgraph 内部隔离不外抛。
- Linux xvfb-run：真实 GLX 上下文，grabFramebuffer 640×480 非空 →
  `.omo/evidence/task-9-offscreen.png`（13KB，57 取样色阶度，edge 色命中 8106 像素）。
- Windows：native（`test_viewport.py` 模块级 os.environ setdefault 覆写，conftest setdefault 兼容）。
- 残余：shaded 体面在 llvmpipe/GL2 上下文可能不填充（需 GL3 着色器通路），基于 edges 渲染与
  item 数量断言不受影响；F4 阶段在三平台真机/远端呈现。

## 关键修复史（勿重犯）
1. 盲抄 numpy allowed（todo-1 leg）后 scope_audit 抓包：numpy 禁面 confine mechanisms 是
   `BACKEND_ROOTS` + 单一 `BACKEND_ALLOWED_PREFIX` 常量——计划承诺 numpy 放行 ui，守卫没接到，
   本 todo 补上；改后 build123d/OCP 仍只能 geom/。
2. 无 numpy 转写（list faces）在实时 GL 油漆时崩（`MeshData.vertexNormals` 需要 ndarray），撇止
   item 层测试的根本原因。UI numpy 必须保留。回归教训：sample 直接读 pyqtgraph 原始约定，不通过二级转写。
3. `_mesh.vertices` 面向 bbox 期望（第一版 z=4）受阻：目前 kernel tessellation 中心在原点。
   相机 fit_view 产物 = bbox center= (0,0,0)，distance≈136.10，FIT_VIEW_MARGIN 常数不硬编码。
4. ruff 一规则套：typings/ 的 N802/N803（第三方 camelCase）经 extend-exclude 解决，禁止 per-file 零-禁
  。`_dialog_saying`-style closure 带 typed self + Decorator helper — 类型层面测试只有 usize, 不出现任何
  ignore。

## 红绿探针（计划要求，tamper→red→restore→green）
- 篡改 `REFRESH_SIGNALS` 去掉 "post_command"：scoped close 选取 coalesced/flange/undo_drops
  三例 → `2 failed, 1 passed`（RED 闭环）。
- 还原：`3 passed`（GREEN 闭环）。

## 验证
- scoped：`QT_QPA_PLATFORM=offscreen uv run pytest tests/ui tests/test_layering.py
  tests/test_scope_audit.py tests/core/test_signals.py tests/geom -q` = **213 passed**。
- `uv run ruff check .` 全过；`uv run ruff format --check .` 182 files 0 改；
  `uv run basedpyright`（全仓）= **0 errors / 0 warnings / 0 notes**。
- 无新增 type:ignore/pyright:ignore（pies 抑制扫描通过 scoped suite 中 test_layering 组含）。
- 视见质量 artifact：`.omo/evidence/task-9-offscreen.png`（640×480；edges 清晰，
  shaded body 残余见「平台兜底阶梯实测」末条）。
