# todo 1 — Phase 1 依赖迁移 + 守卫/NOTICE/CI 适配

计划：`.omo/plans/phase1-desktop-shell.md` todo 1（:118-126）。分支 `phase1-desktop-shell`。

## 变更清单

| 文件 | 变更 |
|---|---|
| `pyproject.toml` | 主依赖 +`PySide6>=6.7,<7` `pyqtgraph>=0.13,<0.14` `PyOpenGL>=3.1,<4`；dev 组 +`pytest-qt>=4.4`；:12-14 注释改写为阶段 1 现实（UI 仅限 src/mycad/ui/）。PyOpenGL 显式声明原因：pyqtgraph 0.13.7 不硬依赖它但 `pyqtgraph.opengl` 导入路径需要 |
| `uv.lock` | 随同步更新（下分辨率） |
| `tests/test_scope_audit.py` | FORBIDDEN_IMPORT_ROOTS +`tkinter`+`wx`（M1 收口）；新增 `UI_ROOTS={"PySide6","shiboken6"}` + `UI_ALLOWED_PREFIX="src/mycad/ui/"`；`scan_forbidden_imports` 加 ui 早退分支；FORBIDDEN_DISTRIBUTIONS 删 `pyside6`/`shiboken6`（删词=唯一合法阀门，注释记录理由）；新增反自证 `test_ui_imports_are_confined_to_the_ui_package` |
| `tests/test_layering.py` | docstring 更新（PySide6 归属说明 + 跨文件守卫分界）；`UI_SRC_ALLOWED_PREFIX`/`UI_SRC_ALLOWED_ROOTS={"numpy"}`；`_is_forbidden_in` 放行 ui 包内恰 numpy；`TESTS_ALLOWED_IMPORT_PREFIXES` +`tests/ui/`；新增 `test_ui_package_must_not_import_geom`（包根禁 mycad.geom） |
| `NOTICE` | 46→54 计数；按字母序新增 8 条目（pyopengl、pyqtgraph、pyside6 家族 5 轮、shiboken6）；Notes 平台段改写（54 三平台恒等、新子树无平台 marker） |
| `.github/workflows/ci.yml` | Linux runner apt GL 离屏库（libgl1/libegl1/libxkbcommon-x11-0/libglib2.0-0） |
| `tests/test_ci_workflow.py` | REQUIRED_TOKENS +`Install GL offscreen libraries`+`libxkbcommon-x11-0` |

## uv sync 分辨率（实测）

pyside6==6.12.0（附 pyside6-addons/essentials/pdf-140/webengine-140 子轮，注意 pdf/webengine 是 `-140` 后缀名）、shiboken6==6.12.0、pyqtgraph==0.13.7、pyopengl==3.1.10、pytest-qt==4.5.0。fs 硬链警告为外观性（cache 跨盘）。

## 闭包真实测量（交错数据校正记录）

- 交接残留数据称闭包 73——**为污染值**（本地 |2>&1 把 uv 的 `Resolved 72 packages` stderr 行混入解析，多出 `resolved` 假词）。以测试同口径（分离流、parse_closure、`-{mycad}`）实测：
  - `uv tree --stdout | parse_closure - {mycad}` = **54**，恰 = 46+8 ✓
  - 8 新名：pyopengl, pyqtgraph, pyside6, pyside6-addons, pyside6-essentials, pyside6-pdf, pyside6-webengine, shiboken6（pyqtgraph 0.13.7 传递依赖仅 numpy，已在列）
- uv.lock sys_platform/os_name marker 全库 6 处，**全为既有**（lib3mf aarch64、colorama win32、pexpect non-win32、psutil cygwin/emscripten）；新子树 0 marker → 54 三平台恒等（NOTICE 已注记）
- pytest-qt 在 dev 组 → 不入闭包 → 不入 NOTICE ✓（test_dev_tools 断言过）

## 许可证取证

- pyside6 家族(5)+shiboken6：`License-Expression='LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only'`（6 轮一致）；NOTICE 提供 Qt LGPLv3 动态链接义务统一块
- pyqtgraph：`License-Expression='MIT'`
- pyopengl：METADATA 仅 generic `BSD License` classifier，**dist-info 无许可证文件**（RECORD 零 licen 条目，实测）→ NOTICE 措辞仿 OCCT 先例：「标识符反映上游项目条款而非 wheel 内陈述」

## 守卫红绿探针（对抗验证）

```
注入 src/mycad/core/document.py: import PySide6
→ tests/test_scope_audit.py::test_no_forbidden_imports  1 failed   [RED 确认]
还原
→ 同一测试                                              1 passed    [GREEN 确认]
grep -rn PySide6 src/mycad/core/ → 0 hits
```

## 与计划文本的诚实偏差（两条）

1. **探针经 test_scope_audit 而非 test_layering**：test_layering 的 FORBIDDEN_MODULES 保持 {build123d,OCP,numpy}（计划禁止在其中加 Qt 禁词），Qt 包级禁令由 test_scope_audit 的 UI_ROOTS 持有——计划验收坦白记录这层所有权分工（core Qt-free 反向自证在 tests/core/test_signals.py:95-105 subprocess 检查，与两条守卫互补）。
2. **NOTICE 新条目为 8 而非恰 4**：PySide6 meta 轮 unavoidably 携带 4 个子轮（addons/essentials/pdf/webengine）+ shiboken6；test_notice 的 fail-closed completeness 断言要求全列（试漏列即红）。计划「恰四」意图按「恰四名产品族」理解：PySide6/shiboken6/pyqtgraph/PyOpenGL 四产品，其轮级展开 8 条全受理。

## scoped 四门（本 todo 验证）

```
uv run pytest tests/test_layering.py tests/test_scope_audit.py tests/test_notice.py tests/test_ci_workflow.py -q
→ 36 passed
uv run ruff check .            → All checks passed!
uv run ruff format --check .   → 164 files already formatted
uv run basedpyright            → 0 errors, 0 warnings, 0 notes
```

禁止面确认：`.mc.json` v1 schema 未触碰；无 PyQt5/VTK/qtpy；core 零 Qt（探针红证）；无 ruff per-file 新增；零 type:ignore（既有守卫未变红）。
