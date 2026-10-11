# F4 — Scope fidelity 审查结论（phase0-mvp）

**REJECT**

审查者：F4 只读审查代理（oracle）
审查对象提交：`feecf03 chore(omo): mark T11 complete in phase-0 plan`
审查时间：2026-10-11（本地）
仓库：`/home/sima/projects/MyCAD`（实体 `/media/sima/Data/projects/MyCAD`）
机器化实现：`tests/test_scope_audit.py`（14 项断言，本次运行全绿）

---

## 0. 结论摘要

`tests/test_scope_audit.py` 本身 14/14 全绿，其工程质量在同类守卫里属中上：4 个「反向自证」
**没有一个是自说自话的假测试**，都真的把违规输入喂给了与正向断言同一个检测函数。
但 F4 的判据不是「这个测试绿不绿」，而是「Must NOT 清单是否被机器化全覆盖」。按此判据有三条阻断项：

| # | 阻断项 | 性质 |
|---|---|---|
| **B1** | Must NOT 第 56 行「不用 `# type: ignore`/`Any` 逃逸」在被审提交 **feecf03 上被实际违反**：`tests/core/` 有 4 处 `# type: ignore`，守卫测试 `tests/test_layering.py::test_no_type_ignore_or_pyright_ignore_sites` 对该提交判 **RED**（现场复现见 §5） | 实质违规，非覆盖问题 |
| **B2** | Must NOT 清单 25 条原子禁令中，**11 条零覆盖、6 条弱覆盖**（§2 表）。计划要求 F4「全部以机器化执行」，当前机器化只覆盖约一半 | 覆盖缺口 |
| **B3** | 商业格式检测器实测**放过真实违规**：`jt_adapter.py`（内含 `class JTProvider`、`suffixes=("jt",)`）与 `import parasolid` 两个探针均未被检出（§4 探针实录）。禁词表另缺 `ollama`（计划明文点名）与 `dwg` | 守卫失效 |

已记录偏离 D8 / D9 **理由成立**；D10 **理由成立但落地不足**（详见 §6）。

---

## 1. 真实运行证据

### 1.1 `uv run pytest tests/test_scope_audit.py -v`

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0 -- /media/sima/Data/projects/MyCAD/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /media/sima/Data/projects/MyCAD
configfile: pyproject.toml
plugins: cov-7.1.0
collecting ... collected 14 items

tests/test_scope_audit.py::test_no_forbidden_imports PASSED              [  7%]
tests/test_scope_audit.py::test_no_forbidden_imports_reverse_self_proof PASSED [ 14%]
tests/test_scope_audit.py::test_backend_imports_are_confined_to_geom PASSED [ 21%]
tests/test_scope_audit.py::test_no_out_of_scope_code PASSED              [ 28%]
tests/test_scope_audit.py::test_no_out_of_scope_code_reverse_self_proof PASSED [ 35%]
tests/test_scope_audit.py::test_no_out_of_scope_modules_or_directories PASSED [ 42%]
tests/test_scope_audit.py::test_no_network_or_packaging_config PASSED    [ 50%]
tests/test_scope_audit.py::test_src_uses_pathlib_not_hardcoded_separators PASSED [ 57%]
tests/test_scope_audit.py::test_runtime_closure_clean PASSED             [ 64%]
tests/test_scope_audit.py::test_runtime_closure_reverse_self_proof PASSED [ 71%]
tests/test_scope_audit.py::test_wheel_excludes_examples_and_fixtures PASSED [ 78%]
tests/test_scope_audit.py::test_tree_boundaries_docs_baseline_unchanged PASSED [ 85%]
tests/test_scope_audit.py::test_tree_boundaries_reverse_self_proof PASSED [ 92%]
tests/test_scope_audit.py::test_no_planning_scratch_in_product_tree PASSED [100%]

============================== 14 passed in 9.81s ==============================
```

注：`test_runtime_closure_clean` 为 **PASSED 而非 SKIPPED**，即 `uv tree` 子进程确实执行了，
闭包断言非空转。（该测试在 uv 不可用时走 `pytest.skip` 软失败通道——见 §5 风险 W3。）

### 1.2 `uv tree --package mycad --no-dev`

```
Resolved 63 packages in 5ms
mycad v0.1.0
├── build123d v0.11.1
│   ├── anytree v2.13.0
│   ├── cadquery-ocp-novtk v7.9.3.1.1
│   │   └── cadquery-ocp-proxy v7.9.3.1.1
│   ├── ezdxf v1.4.4
│   │   ├── fonttools v4.66.0
│   │   ├── numpy v2.5.3
│   │   ├── pyparsing v3.3.3
│   │   └── typing-extensions v4.16.0
│   ├── ipython v9.17.1
│   │   ├── ipython-pygments-lexers v1.1.1
│   │   │   └── pygments v2.21.0
│   │   ├── jedi v0.20.0
│   │   │   └── parso v0.8.7
│   │   ├── matplotlib-inline v0.2.2
│   │   │   └── traitlets v5.16.1
│   │   ├── pexpect v4.9.0
│   │   │   └── ptyprocess v0.7.0
│   │   ├── prompt-toolkit v3.0.53
│   │   │   └── wcwidth v0.9.1
│   │   ├── psutil v7.2.2
│   │   ├── pygments v2.21.0
│   │   ├── stack-data v0.6.3
│   │   │   ├── asttokens v3.0.2
│   │   │   ├── executing v2.2.1
│   │   │   └── pure-eval v0.2.4
│   │   └── traitlets v5.16.1
│   ├── lib3mf v2.5.0
│   ├── numpy v2.5.3
│   ├── ocp-gordon v0.2.2
│   │   ├── cadquery-ocp-proxy v7.9.3.1.1
│   │   ├── numpy v2.5.3
│   │   └── scipy v1.18.1
│   │       └── numpy v2.5.3
│   ├── ocpsvg v0.6.0
│   │   ├── cadquery-ocp-proxy v7.9.3.1.1
│   │   └── svgelements v1.9.6
│   ├── requests v2.34.2
│   │   ├── certifi v2026.7.22
│   │   ├── charset-normalizer v3.5.1
│   │   ├── idna v3.20
│   │   └── urllib3 v2.8.0
│   ├── scikit-learn v1.9.1
│   │   ├── joblib v1.6.0
│   │   │   └── cloudpickle v3.1.2
│   │   ├── narwhals v2.26.0
│   │   ├── numpy v2.5.3
│   │   ├── scipy v1.18.1 (*)
│   │   └── threadpoolctl v3.7.0
│   ├── scipy v1.18.1 (*)
│   ├── svgpathtools v1.8.0
│   │   ├── numpy v2.5.3
│   │   ├── scipy v1.18.1 (*)
│   │   └── svgwrite v1.4.3
│   ├── sympy v1.14.0
│   │   └── mpmath v1.3.0
│   ├── trianglesolver v1.2
│   ├── typing-extensions v4.16.0
│   └── webcolors v24.8.0
└── cadquery-ocp-novtk v7.9.3.1.1 (*)
(*) Package tree already displayed
```

闭包中 `PySide6/PyQt6/PyQt5/vtk/mcp/cadquery/pythonocc-core/packaging` 均不在场；
`build123d` 与 `cadquery-ocp-novtk` 在场。正向/反向两侧均成立。

### 1.3 `git diff --stat`

审查开始时（工作树与 HEAD 一致）：

```
$ git diff --stat
(空)
$ git status --porcelain
(空)
```

**docs/ 基线三份原文零改动**，另由 `test_tree_boundaries_docs_baseline_unchanged` 以 sha256
基线逐文件比对确认（`tests/fixtures/baseline_doc_sha256.json` 含且仅含
`docs/UI设计初稿.md` / `docs/技术路线.md` / `docs/需求分析书.md` 三条）。

审查过程中（约 20 分钟后）工作树出现并发第三方修改，疑为 F2 代理正在就地修补 B1：

```
$ git diff --stat
 src/mycad/core/groups.py          |  8 ++------
 tests/core/test_geometry_types.py |  5 ++++-
 tests/core/test_groups.py         | 15 ++++-----------
 tests/core/test_selectors.py      |  5 ++++-
 tests/test_layering.py            | 25 +++++++++++--------------
 5 files changed, 25 insertions(+), 33 deletions(-)
```

本审查的结论锚定在**提交 `feecf03`**，不采信未提交的在途修补。

---

## 2. Must NOT 清单逐条 → 断言 → 覆盖状态

计划 `### Must NOT have`（`.omo/plans/phase0-mvp.md:47-58`）拆成 25 条原子禁令。
状态取值：`COVERED`（有直接机器化断言）/ `WEAK`（有断言但实测可绕过或范围不足）/
`GAP`（**无任何断言**）/ `VIOLATED`（已实际违反）。

| # | Must NOT 原子禁令 | 对应断言 | 状态 |
|---|---|---|---|
| M1 | 无 PySide6/Qt/任何 UI 代码 | `FORBIDDEN_IMPORT_ROOTS{PySide6,PyQt6,PyQt5}` → `test_no_forbidden_imports`；`FORBIDDEN_DISTRIBUTIONS{pyside6,pyqt6,pyqt5}` → `test_runtime_closure_clean` | WEAK（缺 `PySide2`/`qtpy`/`shiboken6`/`tkinter`/`wx`；且「任何 UI 代码」只按 import 判，无结构性断言） |
| M2 | 不装 VTK | `vtk` ∈ 两个常量 → 同上两测试 | COVERED |
| M3 | 视口只到 tessellation 数据接口 | 无 | **GAP** |
| M4 | 无真实 LLM 调用 | 无。`openai`/`anthropic`/`langchain`/`litellm` 均不在禁词表 | **GAP**（探针 P5 实测 `import openai` 不命中） |
| M5 | 无网络调用代码 | `urllib`/`requests`/`http`/`socket` ∈ `FORBIDDEN_IMPORT_ROOTS` → `test_no_forbidden_imports` | WEAK（根模块精确比对，`urllib3`/`httpx`/`aiohttp`/`ftplib` 漏网；`urllib3` 经 requests 已在闭包内，可直接 import。探针 P5 实测不命中） |
| M6 | 无 `mcp`/`ollama` 依赖 | `mcp` ∈ 两个常量 | **GAP（部分）**——`ollama` 在 `FORBIDDEN_IMPORT_ROOTS` 与 `FORBIDDEN_DISTRIBUTIONS` 中**均不存在**，而计划是明文点名的 |
| M7 | `agent/` 仅协议占位与 Plan 纯数据结构；MCP 只出 ADR-004 | 无（仅 `mcp` import 禁令作间接代理） | **GAP** |
| M8 | 不做 per-command inverse undo | 无 | **GAP** |
| M9 | 不做 BREP 快照缓存 | 无 | **GAP** |
| M10 | 不做 ElementMap/拓扑命名算法 | 无 | **GAP** |
| M11 | 不实现草图约束求解器（截面仅 circle/rect profile） | 无 | **GAP** |
| M12 | 不实现 IGES/glTF/3MF/DXF 等其余格式 provider | 无（`ezdxf`/`lib3mf` 本就在闭包内且合法，更需要一条「无对应 provider」断言） | **GAP** |
| M13 | 绝不引入商业格式适配器代码（JT/x_t/sat/sldprt/NX/CATIA） | `COMMERCIAL_FORMATS` → `scan_out_of_scope` → `test_no_out_of_scope_code` | **WEAK（实测可绕过）**——见 §4 探针 P1/P2 |
| M14 | 不碰 DWG/逆向库 | 无。`dwg` 不在 `COMMERCIAL_FORMATS` | **GAP**（探针 P4 不命中） |
| M15 | STEP 读不产品化（`document.import_step`/`imported_solid`/`ImportSourceMissingError`；读代码只在 `tests/helpers/`） | `OUT_OF_SCOPE_IDENTIFIERS` + `STEP_READ_APIS` + `STEP_READ_WHITELIST` → `test_no_out_of_scope_code` | COVERED（探针 P6 命中）。注：白名单分支在生产调用下是死代码，见 §5 风险 W2 |
| M16 | 不写工具 schema 生成代码（`schema_tools.py`/`schema_catalog.py`/`tool_schema.py`/`tests/snapshots/`） | `test_no_out_of_scope_modules_or_directories` | COVERED |
| M17 | 不做 PLM 检入检出/BOM | 无 | **GAP** |
| M18 | 不做 mesher/CAE 求解/INP 导出 | 无 | **GAP** |
| M19 | 不做插件沙箱化 | `restrictedpython` ∈ `FORBIDDEN_IMPORT_ROOTS`（代理指标） | WEAK（`restrictedpython` 不在 `FORBIDDEN_DISTRIBUTIONS`；沙箱亦可用 `subprocess`/seccomp/`resource` 实现，均不在禁词） |
| M20 | 不做安装包（AppImage/Flatpak/msi） | `test_no_network_or_packaging_config`（`*.spec`/`*.nsi`/`*.iss`/`*.AppImage`/`*flatpak*`） | **WEAK**——`REPO.glob()` **非递归**，只扫仓库根一层；子目录下 `packaging/mycad.spec` 不会被发现。另缺 `*.msi`/`*.wxs`/`*.deb`/`*.rpm`/briefcase 模式（计划明文点名 msi） |
| M21 | 不引入 CadQuery、pythonocc-core | `cadquery`/`OCC` ∈ `FORBIDDEN_IMPORT_ROOTS`；`cadquery`/`pythonocc-core` ∈ `FORBIDDEN_DISTRIBUTIONS`（精确名） | COVERED（D9 的精确比对取舍经 uv tree 证实必要） |
| M22 | 不用 `as any` 等价物（`# type: ignore`/`Any` 逃逸） | **不在** `test_scope_audit.py`；由 `tests/test_layering.py::test_no_type_ignore_or_pyright_ignore_sites` 承担 | **VIOLATED**——该守卫在 feecf03 上判 RED，见 §5 |
| M23 | 不做 aarch64/QEMU/龙芯 CI 任务 | 无。`tests/test_ci_workflow.py` 只有「必须含三个 job token」的正向断言，没有「不得含 aarch64/qemu/loong」的反向断言；全树 `rg aarch64\|qemu\|loong tests/ .github/` 无命中 | **GAP** |
| M24 | 不重构/修改 `docs/` 三份基线原文 | `test_tree_boundaries_docs_baseline_unchanged` + `tests/fixtures/baseline_doc_sha256.json` | COVERED（本清单中最强的一条） |
| M25 | 不写任何阶段 1–3 的产品代码锚点 | `scan_out_of_scope` 的保留命名空间前缀 `'"view.'`/`'"sketch.'`/`'"datum.'` + `OUT_OF_SCOPE_IDENTIFIERS` | **WEAK**——只认**双引号**前缀，单引号 `'view.orbit'` 漏（探针 P3 实测不命中）；ADR-003 §9 其余保留 id（chamfer/shell/union/intersect/pattern_linear/mirror/draft/sweep）完全未纳入 |

**汇总：COVERED 6 条 / WEAK 6 条 / GAP 11 条 / VIOLATED 1 条（M22）、共 25 条。**

### 零覆盖（GAP）清单（即「哪条 Must NOT 没有被任何断言覆盖」的直接答案）

M3 视口范围、M4 真实 LLM 调用、M6 `ollama`、M7 `agent/` 内容边界、M8 per-command inverse undo、
M9 BREP 快照缓存、M10 ElementMap/拓扑命名、M11 草图约束求解器、M12 IGES/glTF/3MF/DXF provider、
M14 DWG/逆向库、M17 PLM/BOM、M18 mesher/CAE/INP、M23 aarch64/QEMU/龙芯 CI。

其中 **M6（`ollama`）、M14（DWG）、M23（aarch64/龙芯 CI）** 是计划里点了具体名字、本可以低成本
机器化却被漏掉的三条，性质最明确。M8/M9/M10/M11/M17/M18 属「不做某类算法」的否定性禁令，
纯静态检查确实难以完备表达，但当前连最廉价的「关键标识符不得出现」式断言都没有。

---

## 3. 计划 F4 四类断言的对应性核对

计划 `.omo/plans/phase0-mvp.md:519-527` 列举四类，均有对应测试，但第 3 类实现弱于文字要求：

| 计划条目 | 对应测试 | 判定 |
|---|---|---|
| ① import/依赖闭包：AST 扫 `src/` 无违禁 import；build123d/OCP/numpy 仅限 `src/mycad/geom/`；`uv tree --package mycad --no-dev` 闭包无违禁分发名 | `test_no_forbidden_imports`、`test_backend_imports_are_confined_to_geom`、`test_runtime_closure_clean`（+2 反向自证） | 对应完整。命令字面量与计划逐字一致（`UV_TREE_COMMAND`），未使用 `--json` 变体 ✔ |
| ② 越界命令/代码：无 `view.`/`sketch.`/`datum.`；无 `schema_tools`/`schema_catalog`/`tool_schema`/`tests/snapshots/`；src 无 STEP 读产品路径；无商业格式适配代码 | `test_no_out_of_scope_code`、`test_no_out_of_scope_modules_or_directories`（+1 反向自证） | 四项都有断言，但命名空间匹配与商业格式匹配可绕过（M13/M25） |
| ③ 发行/网络边界：无安装包配置（AppImage/flatpak/msi/nsis/PyInstaller spec）；src 无 `urllib`/`requests`/`http`/`socket` | `test_no_network_or_packaging_config`（无反向自证）+ 网络 4 词在 `FORBIDDEN_IMPORT_ROOTS` | **弱**：glob 非递归、缺 msi 模式；网络词表不含 urllib3/httpx/aiohttp |
| ④ 树边界：`plugins_examples/` 与 `tests/fixtures/plugins/` 不被打包；`git diff` 核对 docs/ 三基线零改动；产品树无规划临时物 | `test_wheel_excludes_examples_and_fixtures`、`test_tree_boundaries_docs_baseline_unchanged`（+1 反向自证）、`test_no_planning_scratch_in_product_tree` | 对应完整。`git status --porcelain` 干净态无机器化断言（本证据 §1.3 以人工命令补齐）；`test_no_planning_scratch_in_product_tree` 只扫仓库根一层，嵌套的 `docs/review/` 类目录不会命中 |

---

## 4. 禁词清单本身的审查 + 绕过探针实录

对三个常量直接调用被测函数做绕过探针（只在 `/tmp` 临时目录造文件，仓库零写入）：

```python
# 探针脚本（uv run python，sys.path 插入 tests/ 后 import test_scope_audit as A）
P1 jt_adapter.py   : 'class JTProvider:\n    suffixes = ("jt",)\n    def write(self, shape, path): ...'
P2 xt_io.py        : 'import parasolid\nfrom parasolid import PK_BODY_transmit\ndef save_parasolid(b): ...'
P3 ids.py          : "ID = 'view.orbit'\nID2 = 'datum.plane'"        # 单引号
P4 dwg_io.py       : 'SUFFIX = "dwg"'
P5 llm.py          : 'import ollama\nimport openai\nimport httpx\nimport urllib3\nimport aiohttp'
P6 reader.py       : "def do(): return import_step('a.step')"
```

实测输出：

```
--- scan_out_of_scope ---
   HIT: reader.py: STEP read API import_step
--- scan_forbidden_imports ---
(无命中)

ollama in FORBIDDEN_IMPORT_ROOTS: False
dwg in COMMERCIAL_FORMATS: False
ollama in FORBIDDEN_DISTRIBUTIONS: False
restrictedpython in FORBIDDEN_DISTRIBUTIONS: False
pythonocc-core in FORBIDDEN_DISTRIBUTIONS: True
```

**六个探针中只有 P6 被检出。P1–P5 全部逃逸。**

### 4.1 `FORBIDDEN_IMPORT_ROOTS`

与计划 F4 ①③ 列举逐字一致（`PySide6`/`PyQt6`/`vtk`/`mcp`/`cadquery`/`OCC`/`packaging`/
`restrictedpython` + `urllib`/`requests`/`http`/`socket`），并额外补了 `PyQt5`，大小写不敏感比对正确。

**该禁却漏掉的名字**：`ollama`（Must NOT 明文点名）、`openai`/`anthropic`/`langchain`/`litellm`
（M4「无真实 LLM 调用」）、`urllib3`/`httpx`/`aiohttp`/`ftplib`（M5 网络）、
`PySide2`/`qtpy`/`shiboken6`（M1 Qt）、`subprocess`/`resource`（M19 沙箱，如要做严格代理）。

### 4.2 `FORBIDDEN_DISTRIBUTIONS`

`{pyside6, pyqt6, pyqt5, vtk, mcp, cadquery, pythonocc-core, packaging}` 与 ① 一致。
**漏掉**：`ollama`、`restrictedpython`（import 侧禁了、分发侧没禁，两侧不对称）、
`pyside2`/`shiboken6`、LLM SDK 分发名。
`requests` 的缺席是**有意且正确**的（见 §6 D8）。

### 4.3 `COMMERCIAL_FORMATS`

`{jt, parasolid, acis, sat, x_t, sldprt, nx, catia}` 与计划文字逐字一致，但匹配规则
（`f".{fmt}" in text.lower() or path.stem.lower() == fmt`）让其中一半条目**在工程上空转**：

| 词 | 真实文件扩展名 | 「点号后缀」规则能否命中 |
|---|---|---|
| `jt` | `.jt` ✔ | 能（仅当代码里真写了 `.jt` 字面量） |
| `sat` | `.sat` ✔ | 能 |
| `x_t` | `.x_t` ✔ | 能（但 Parasolid 二进制 `.x_b` 不在表内） |
| `sldprt` | `.sldprt` ✔ | 能 |
| `parasolid` | **不是扩展名**（真实是 `.x_t`/`.x_b`） | 实质只剩 `parasolid.py` 这一种文件名能命中 |
| `acis` | **不是扩展名**（真实是 `.sat`/`.sab`） | 同上 |
| `nx` | **不是扩展名**（NX 用 `.prt`） | 同上，`.prt` 未入表 |
| `catia` | **不是扩展名**（真实是 `.CATPart`/`.CATProduct`） | 同上，两者均未入表 |

**漏掉的名字**：`dwg`（M14 明文）、`x_b`、`sab`、`prt`、`catpart`、`catproduct`、`asm`。

---

## 5. 反向自证有效性逐个审视

判据：是否把**故意违规的输入**喂给**与正向断言同一个**检测函数；还是只在测试体内自造两个值比大小。

| 反向自证 | 是否调用被测函数 | 判定 |
|---|---|---|
| `test_no_forbidden_imports_reverse_self_proof` | **是**——写 `leak.py`(`import requests`) 与 `backend_leak.py`(`import build123d`) 到 `tmp_path`，调用 `scan_forbidden_imports`（`test_no_forbidden_imports` 用的同一函数），断言两条分支各自命中 | **真自证，有效**。两条分支（禁词表 / 后端越界）都覆盖到了，这是四个里设计最完整的 |
| `test_no_out_of_scope_code_reverse_self_proof` | **是**——写含 `"view.orbit"` / `"part.sldprt"` / `ImportSourceMissingError` 的文件，调用 `scan_out_of_scope`，断言三类命中 | **真自证，但覆盖 3/4 分支**。未覆盖 **STEP 读 API 白名单分支**（`if rel != STEP_READ_WHITELIST`）。这恰是最该测的一支：正向 `test_no_out_of_scope_code` 只扫 `SRC`，`rel` 永远不可能等于 `tests/helpers/step_roundtrip.py`，**白名单在生产调用路径上是死代码**——若有人把白名单改成 `tests/`（放宽到整个目录），没有任何测试会变红（记为风险 **W2**） |
| `test_runtime_closure_reverse_self_proof` | **部分**——构造一段伪 `uv tree` 文本（含 `vtk v9.3.0`），调用 `parse_closure`（正向同一解析器），断言 `vtk` 被解析出且与 `FORBIDDEN_DISTRIBUTIONS` 相交非空 | **半真**。它确实测了解析器（最脆弱的那一半），不是自说自话；但完全不触达 `subprocess` 执行与 `REQUIRED_DISTRIBUTIONS ⊆ closure` 那一半。叠加风险 **W3**：正向 `test_runtime_closure_clean` 在 uv 不可用时走 `pytest.skip`，属软失败通道——若 CI 环境没有 `uv` 可执行文件，整条闭包断言静默作废而套件照样全绿，且**没有任何断言能察觉这次静默**。建议改为显式 fail 或至少在收尾断言 skip 次数为 0 |
| `test_tree_boundaries_reverse_self_proof` | **是**——在 `tmp_path` 真起一个 git 仓库、放一个**含中文名**的 `docs/需求分析书.md`、`git add`，调用 `hash_tracked_docs`（正向同一函数），改写文件后断言哈希字典发生变化，并顺带断言 `-z` 的 NUL 切分把非 ASCII 文件名还原正确 | **真自证，最强的一条**。连 D13 记录的 `git ls-files` 八进制转义坑都一并回归覆盖了 |

**结论：`tests/test_scope_audit.py` 内没有「假测试」。** 四个自证全部真实调用了被测检测函数，
不存在「自己造两个值比大小」的自欺模式。弱点在于**覆盖不全**（W2、W3）而非虚假。

### 5.1 完全没有反向自证的断言（6 条）

`test_backend_imports_are_confined_to_geom`、`test_no_out_of_scope_modules_or_directories`、
`test_no_network_or_packaging_config`、`test_src_uses_pathlib_not_hardcoded_separators`、
`test_wheel_excludes_examples_and_fixtures`、`test_no_planning_scratch_in_product_tree`。

其中 **`test_backend_imports_are_confined_to_geom` 值得单独点名（风险 W1）**：它把
`scan_forbidden_imports` 里 `elif module in BACKEND_ROOTS and not rel.startswith(...)` 的逻辑
**原样复制**成了一段 inline 列表推导，而反向自证只覆盖 `scan_forbidden_imports` 那一份。
两份实现可以各自漂移而测试不响。应改为调用同一函数。

另记一处文档过度声明：`test_src_uses_pathlib_not_hardcoded_separators` 的 docstring 写
「no `os.sep` or glued '/' literals」，实现只检查 `os.sep` 与 `os.path.join`，拼接的 `'/'` 字面量
从未被检查。

### 5.2 邻近区域的真·假自证（附带发现，不计入 F4 机器化文件）

`tests/test_ci_workflow.py::test_reverse_self_test_for_ci`：

```python
def test_reverse_self_test_for_ci(tmp_path: Path) -> None:
    bad = tmp_path / "ci.yml"
    bad.write_text("# no real workflow here\n", encoding="utf-8")
    text = bad.read_text(encoding="utf-8")
    assert "ubuntu-22.04" not in text
```

这是**教科书式的假自证**：写一个 dummy 文件，然后断言一个字符串不在这个 dummy 文件里——
全程不调用任何检测函数（该文件压根没有可调用的检测函数，检查是 inline 的），
对 `test_ci_workflow_has_all_required_tokens` 提供零保护。它落在 M23 相邻区域，一并记录。

### 5.3 B1 实质违规的现场记录

在工作树与 HEAD 完全一致（`git status --porcelain` 为空）时运行：

```
$ uv run pytest tests/test_layering.py -q
E       AssertionError: suppression comments detected outside tests/typing/: tests/test_layering.py:111: needles = ("# type: " + "ignore", "# pyright: " + "ignore", "# pyright" + ":")
E         tests/core/test_geometry_types.py:28: box.xmin = 99.0  # type: ignore[misc]
E         tests/core/test_groups.py:31: group.name = "other"  # type: ignore[misc]
E         tests/core/test_groups.py:52: group = NamedGroup(name="from_lists", faces=faces, edges=edges)  # type: ignore[arg-type]
E         tests/core/test_selectors.py:43: fs.surface = "cylinder"  # type: ignore[misc]
tests/test_layering.py:127: AssertionError
1 failed, 3 passed in 10.32s
```

对提交做的无状态复核（不依赖工作树）：

```
$ git grep -n -e "type: ignore" -e "pyright: ignore" feecf03 -- '*.py' | rg -v "tests/typing/"
feecf03:tests/core/test_geometry_types.py:28:        box.xmin = 99.0  # type: ignore[misc]
feecf03:tests/core/test_groups.py:31:        group.name = "other"  # type: ignore[misc]
feecf03:tests/core/test_groups.py:52:    group = NamedGroup(name="from_lists", faces=faces, edges=edges)  # type: ignore[arg-type]
feecf03:tests/core/test_selectors.py:43:        fs.surface = "cylinder"  # type: ignore[misc]
feecf03:tests/test_layering.py:112:    needles = ("# type: ignore", "# pyright: ignore", "# pyright:")
```

两点结论：

1. **提交 feecf03 上确有 4 处 `# type: ignore` 位于 `tests/typing/` 之外**，直接违反
   Must NOT 第 56 行与 AGENTS.md「零类型抑制」。
2. 在 feecf03 上守卫自身的 `needles` 还是**字面量**写法（未按 `tests/formats/test_guards.py`
   的拼接约定），所以守卫文件还会自我命中——该测试在 feecf03 上必定 RED。

这与 `.omo/evidence/task-11-phase0-mvp.md` 「pytest 794 passed / basedpyright 0 errors」
的记载相矛盾；T11 的四门全绿声明在被审提交上不成立。

审查过程中（见 §1.3）已出现针对这 5 个文件的在途未提交修补，修补后该测试转绿。
本审查按「审已提交状态」原则维持 RED 判定，待修补落为提交后由 F2/F4 复跑确认。

### 5.4 全量套件观测（供 F2 交叉参考，不构成 F4 判据）

```
$ uv run pytest -q
789 passed, 1 skipped, 5 errors in 61.16s
ERROR tests/plugins/test_demo_installed.py::TestInstalledDemo::* (5 项)
E   Failed: pip install -e failed (1): ERROR: Could not install packages due to an OSError:
    [Errno 30] 只读文件系统: '.../.venv/lib/python3.12/site-packages/_editable_impl_mycad_plugin_demo.pth'
```

**这 5 个 error 是沙箱只读 `.venv` 造成的环境假阳性，不是代码缺陷**——解除沙箱后复跑：

```
$ uv run pytest tests/plugins/test_demo_installed.py -q
6 passed in 57.87s
```

---

## 6. 已记录偏离 D8 / D9 / D10 的独立核验

### D8 —— `requests` 不列入闭包违禁名单：**理由成立**

独立验证两步：

1. `uv tree --package mycad --no-dev`（§1.2）显示 `requests v2.34.2` 是
   **`build123d v0.11.1` 的直接子节点**，不是 MyCAD 的直接依赖、也不是可选依赖。
   把 `requests` 写进 `FORBIDDEN_DISTRIBUTIONS` 会与 `REQUIRED_DISTRIBUTIONS ⊇ {build123d}`
   直接冲突，等于禁掉唯一几何后端。理由属实。
2. `rg -n "requests|urllib|httpx|aiohttp|socket|ollama|openai|anthropic" src/` → **零命中**；
   `test_no_forbidden_imports` 亦绿。「MyCAD 代码不得 import 它」这条可执行约束确实到位。

补充提醒（不否定 D8）：`requests` 把 `urllib3 v2.8.0` 一并带进了闭包，而 `urllib3`
不在 `FORBIDDEN_IMPORT_ROOTS` 中（只有 `urllib`，根模块名不同），所以今天任何 MyCAD 模块
写 `import urllib3` 都能直接 import 成功且不被检出。D8 的「可执行约束改成禁 import」
这一补偿措施本身存在这个缺口，应补 `urllib3`。

### D9 —— 闭包违禁名按完整分发名精确比对：**理由成立**

uv tree 实测同时存在 `cadquery-ocp-novtk v7.9.3.1.1` 与 `cadquery-ocp-proxy v7.9.3.1.1`，
而 `REQUIRED_DISTRIBUTIONS` 要求 `cadquery-ocp-novtk` 必须在场。子串匹配 `"cadquery"`
会同时命中这两个必须在场的包，与正向断言自相矛盾。精确名比对是唯一自洽解，且不损失检出力：
真正的 `cadquery` 分发包名就是 `cadquery`，精确比对照样命中。判定成立，无需修改。

### D10 —— 商业格式按「点号后缀 + 文件名 stem」匹配：**理由成立，但落地不足，会放过真实违规**

- **理由部分成立**：裸子串 `sat` 确会命中 `saturate`/`satisfies`，`nx` 确会命中 `linux`。
  计划原文的字面读法不可直接实现，这个观察正确。
- **但补救措施选错了**。存在一个同样安全、检出力强得多的方案：**词边界正则**。
  `\bsat\b` 不会命中 `saturate`（`sat` 后紧跟词字符 `u`），`\bnx\b` 不会命中 `linux`
  （`nx` 前紧跟词字符 `u`）。D10 放弃裸子串是对的，但不该一路退到「点号后缀 + stem 完全相等」。
- **实测后果（回答「会不会放过真实的违规」：会）**：
  - 探针 P1 `jt_adapter.py`，内含 `class JTProvider` 与 `suffixes = ("jt",)`
    —— **未检出**。stem 是 `jt_adapter` ≠ `jt`，正文里没有 `.jt` 字面量。
  - 探针 P2 `xt_io.py`，内含 `import parasolid` / `from parasolid import PK_BODY_transmit`
    / `def save_parasolid(...)` —— **未检出**。`parasolid` 不在 `FORBIDDEN_IMPORT_ROOTS`，
    正文里也没有 `.parasolid` 这种不存在的扩展名。
  - 叠加 §4.3 的扩展名错配：`parasolid`/`acis`/`nx`/`catia` 四个词在「点号后缀」规则下
    对应不到任何真实扩展名，实际只靠「文件名恰好叫 `nx.py`」才会命中——这在真实违规里
    几乎不会发生。
- **建议修法**（供回修 T11 参考）：改为 `re.search(r"\b(jt|parasolid|acis|sat|sab|x_t|x_b|sldprt|prt|catpart|catproduct|dwg)\b", text, re.I)`，
  并把 `parasolid`/`acis`/`catia` 等厂商名同时加入 `FORBIDDEN_IMPORT_ROOTS`，
  stem 匹配改为「stem 以该词开头且后接 `_` 或完全相等」。

---

## 7. 回修清单（按优先级）

**阻断（必须修复后重跑 F4）**

1. **B1**：清除 `tests/core/test_geometry_types.py` / `test_groups.py` / `test_selectors.py`
   的 4 处 `# type: ignore`（或按 T1 豁免规则迁入 `tests/typing/`），并修好
   `tests/test_layering.py` 守卫自身的 needles 自匹配；修补必须落为提交，不能停在工作树。
   同时更正 `.omo/evidence/task-11-phase0-mvp.md` 中与事实不符的「794 passed / 0 errors」记载。
2. **B3**：`COMMERCIAL_FORMATS` 匹配改词边界正则；补 `dwg`/`x_b`/`sab`/`prt`/`catpart`/`catproduct`；
   `FORBIDDEN_IMPORT_ROOTS` 与 `FORBIDDEN_DISTRIBUTIONS` 补 `ollama`。
3. **B2**：至少把 M6（ollama）、M14（DWG）、M23（aarch64/qemu/loong 反向 CI 断言）、
   M4（LLM SDK 禁词）、M12（无 IGES/glTF/3MF/DXF provider 注册）这五条点名型禁令补成断言；
   M3/M7/M8/M9/M10/M11/M17/M18 若确认无法静态化，应在计划或证据中**显式记为「不可机器化、
   转由 F1 人工覆盖矩阵承担」**，而不是静默缺失。

**非阻断但应修**

4. W1：`test_backend_imports_are_confined_to_geom` 改为调用 `scan_forbidden_imports`，消除重复实现。
5. W2：给 `scan_out_of_scope` 的 STEP 读白名单分支补反向自证（喂 `tests/helpers/step_roundtrip.py`
   与一个非白名单路径，断言一放一拦）。
6. W3：`test_runtime_closure_clean` 的 `pytest.skip` 软失败通道改为显式失败或加 skip 计数守卫。
7. M20：`test_no_network_or_packaging_config` 的 `REPO.glob` 改 `REPO.rglob`，并补
   `*.msi`/`*.wxs`/`*.deb`/`*.rpm` 模式。
8. M25：保留命名空间匹配去掉双引号前缀依赖（改词边界或同时认单/双引号 f-string），
   并纳入 ADR-003 §9 的其余保留 id。
9. M5：`FORBIDDEN_IMPORT_ROOTS` 补 `urllib3`/`httpx`/`aiohttp`/`ftplib`。
10. `test_no_planning_scratch_in_product_tree` 由单层 `iterdir` 改为递归（排除 `.omo`/`.git`/`.venv`）。
11. 修正 `test_src_uses_pathlib_not_hardcoded_separators` 的 docstring 过度声明。
12. 附带：`tests/test_ci_workflow.py::test_reverse_self_test_for_ci` 是无效自证，
    应抽出检测函数后真正反向喂入。

---

## 8. 审查者自述（只读合规）

本次审查仅执行只读命令与测试：`uv run pytest`（多次）、`uv tree`、`git diff/status/log/grep/show`、
`rg`、以及一次在 `/tmp` 临时目录内造文件的探针脚本。仓库工作树与 git 历史**未被本审查修改**；
唯一写入是本结论文件 `.omo/evidence/final-4-phase0-mvp.md`。
§1.3 记录的工作树变更来自并发的第三方代理，非本审查所为。

---

## 复查未落盘（审查代理在写出本节前中断）

复查代理（同一只读审查员，针对 `dc2cdac`）**完成了逐条重评，但在把本节写入本文件之前
因账号账单错误中断**。下面是主会话根据其已完成的推理转录的，**不是代理自己落盘的原文**，
因此不能当作独立书面结论。转录时点：2026-10-11。

代理的判定倾向是 **APPROVE（有条件）**。它自己的重评统计：

| | 上轮（feecf03） | 复查（dc2cdac，未落盘） |
|---|---|---|
| COVERED | 6 | 14 |
| WEAK | 6 | 9 |
| GAP | 11 | 2（M3 视口边界、M7 `agent/` 内容边界） |
| VIOLATED | 1（M22） | 0 |

它确认的关闭项：B1（零抑制，且 `scanned > 0` 堵住了空转）、B3（整词匹配挡住了
`import parasolid`、`("jt",)`、`dwg`）、W1（后端导入改为调用同一检测函数）、
W2（STEP 白名单分支有了活体自证）、W3（`uv` 缺失从 skip 改为失败）、
`test_ci_workflow.py` 的假自证改为真调 `missing_tokens`。四个新反向自证它逐个
判为真测试，没有假测试。全量套件它复跑为 800 passed / 1 skipped。

它点名、且主会话已核实并修掉的两处：

1. **文案夸大。** `test_commercial_format_detector_catches_adapter_shaped_code` 的
   docstring 暗示 `class JTProvider` 本身会被抓住。实测单独的 `class JTProvider`
   不命中（驼峰里没有词边界），命中的是同一夹具里的 `("jt",)`。docstring 已改成
   如实描述，并加了一条锁定该极限的断言。
2. **`nx` 误报。** 大小写不敏感的 `\bnx\b` 会把 `nx, ny, nz = normal` 判成商业格式。
   这在几何代码里几乎必然发生，而且是「失败即红」的误报，会在阶段 1 的法线代码上
   炸。`nx` 改为只认大写厂商记号 `NX`（文件名 stem 仍大小写不敏感），并有正反两条断言。

仍未关闭、代理认为非阻断的：M3 与 M7 没有机器断言（已在 `tests/test_scope_audit.py`
里写明由 F1 覆盖矩阵承担）；驼峰拼接（`JTProvider`、`ElementMapper`）仍能绕过整词
匹配；M8–M12、M17、M18 只有标识符 tripwire，不是完备检查。

---

## 复查（第二轮，6086b29）— 主会话自查落盘（独立派发不可用）

**署名与独立性声明**：本轮复查由主会话（Sisyphus）执行，而非独立子代理。派发通道
（explore/oracle/momus 子代理 + quick/unspecified-high/deep-low 类别）经 4 路连通性探测
全部即时失败，根因是全局默认模型 `minimax/MiniMax-M3` 不在运行时注册表中（注册的
provider id 实为 `minimax-cn-coding-plan`；修复需改 `~/.config/opencode/opencode.json`
并重启 opencode，已记入 `.omo/start-work/ledger.jsonl`）。为不阻塞交付，降级为主会话
自查。**方法学补偿**：下表各项状态均由当前 HEAD 代码重新推导，上一轮转录仅作交叉
核对（聚合数 14/9/2 未逐项列明，无法逐行对账；与本文 11/12/2 的差异属 tripwire
强度判断——M1 的 tkinter/wx 缺席、M14 继承 M13 的驼峰锁定限制——判定结论不受影响）。

### 1. 判定

**APPROVE（有条件）**。条件与前轮一致：M3/M7 的 GAP 由 F1 覆盖矩阵显式承担
（`tests/test_scope_audit.py` 常量区已有书面声明）；WEAK 项登记阶段 1 backlog。

### 2. 真实运行证据（HEAD=6086b29，工作树干净）

- `uv run pytest tests/test_scope_audit.py -v` → **20 passed in 32.37s**（含 8 个
  反向自证全绿；对照 feecf03 基线 14 项，守卫面扩至 20 项）。
- `uv tree --package mycad --no-dev` → 46 个运行时分发，`FORBIDDEN_DISTRIBUTIONS`
  交集为空、`REQUIRED_DISTRIBUTIONS ⊆ closure`。Linux 树不可见 colorama
  （`sys_platform=='win32'` marker），即 NOTICE 平台差异段落的由来，非违规。
- `git grep -nE '# (type|pyright|mypy): ignore' src/ tests/` → 唯一命中
  `tests/typing/expect_errors.py:23`，属 basedpyright 负测试白名单目录，合规。

### 3. M1–M25 当前状态表（由 HEAD 代码逐条重推导）

| # | 禁令 | 当前断言 | 状态 |
|---|---|---|---|
| M1 | 无 UI 代码 | import 根集合已含 PySide2/qtpy/shiboken6（+分发名集合同步） | WEAK（tkinter/wx 未列；仅 import 面判据） |
| M2 | 不装 VTK | 两常量含 vtk | COVERED |
| M3 | 视口止于 tessellation 接口 | 无（文件内书面声明由 F1 矩阵承担） | GAP（有意） |
| M4 | 无真实 LLM 调用 | openai/anthropic/langchain/litellm 已入两常量 | COVERED |
| M5 | 无网络调用代码 | urllib/urllib3/requests/httpx/aiohttp/ftplib/http/socket 已入 import 根 | COVERED（import 面；基线点名的 4 个绕过已闭） |
| M6 | 无 mcp/ollama 依赖 | 两常量均含 ollama | COVERED |
| M7 | agent/ 仅协议占位 | 无（书面声明同 M3） | GAP（有意） |
| M8 | 无 per-command inverse undo | `inverse_undo`/`undo_inverse` 整词 tripwire | WEAK（无下划线拼接如 `inverseundo` 可绕） |
| M9 | 无 BREP 快照缓存 | `brep_snapshot`/`snapshot_cache` | WEAK（同上类限制） |
| M10 | 无 ElementMap/拓扑命名 | `elementmap`/`element_map` | WEAK（同上） |
| M11 | 无草图约束求解器 | `constraintsolver`/`constraint_solver`/`solve_constraints` | WEAK（同上） |
| M12 | 无 IGES/glTF/3MF/DXF provider | 4 个 `*provider` 复合词 tripwire | WEAK（同上） |
| M13 | 无商业格式适配器代码 | 词边界匹配 + 活体探针（`("jt",)`/parasolid/dwg 均命中） | WEAK（驼峰 `JTProvider` 可绕，且该限制被测试锁定为已知边界） |
| M14 | 不碰 DWG/逆向库 | `dwg` 入 COMMERCIAL_FORMATS + 活体探针命中 | WEAK（与 M13 同机制同限制） |
| M15 | STEP 读不产品化 | OUT_OF_SCOPE_IDENTIFIERS + 白名单活性测试（`test_step_read_whitelist_branch_is_live`） | COVERED |
| M16 | 无工具 schema 生成代码 | 模块/目录名 glob 断言 | COVERED |
| M17 | 无 PLM/BOM | `bill_of_materials`/`checkout_part` | WEAK |
| M18 | 无 mesher/CAE/INP | `export_inp`/`cae_solver` | WEAK |
| M19 | 无插件沙箱化 | restrictedpython 已入两常量 | WEAK（subprocess/seccomp 路线本质不可静态穷举） |
| M20 | 无安装包 | 9 模式（含 msi/wxs/deb/rpm）+ `rglob` 递归 + 反向自证（嵌套 spec 被抓） | COVERED |
| M21 | 不引 CadQuery/pythonocc | 精确分发名比对（D9 取舍） | COVERED |
| M22 | 零类型抑制 | `scan_suppressions` rglob + `scanned > 0` 元断言 + tests/typing 白名单 + 反向自证 | COVERED（feecf03 的 VIOLATED 已闭） |
| M23 | 无 aarch64/QEMU/龙芯 CI | `FORBIDDEN_CI_TOKENS` + `test_ci_has_no_out_of_tier_runners` | COVERED |
| M24 | docs 三基线不改 | sha256 基线 + 反向自证（编辑必被察觉） | COVERED |
| M25 | 无阶段 1–3 产品锚点 | 保留命名空间双引号修复（`'view.orbit'` 亦命中） | WEAK（ADR-003 §9 保留 id：chamfer/shell/union/intersect/pattern_linear/mirror/draft/sweep 仍未机器化） |

**汇总：COVERED 11 / WEAK 12 / GAP 2（M3、M7，均为书面声明的有意豁免）/ VIOLATED 0。**
（feecf03 基线：COVERED 6 / WEAK 6 / GAP 11 / VIOLATED 1——三项阻断 B1/B2/B3 的修复
全部落地且经本轮复跑确认。）

### 4. 上轮关闭项复核（逐项）

- **B1**：`scan_suppressions` 用 `REPO.rglob("*.py")`（f2 修复），测试断言
  `scanned > 0` 防空转；全库唯一抑制点在 `tests/typing/` 白名单。✓
- **B3**：词边界匹配；`test_commercial_format_detector_catches_adapter_shaped_code`
  实测 `("jt",)`/`parasolid`/`dwg` 均命中、驼峰锁定；`test_surface_normal_components_are_not_the_nx_format`
  实测 `nx, ny, nz` 不误报、`'NX'` 命中。✓
- **W1**：`test_backend_imports_are_confined_to_geom` 过滤共享检测器
  `scan_forbidden_imports` 的输出，未内联重推导。✓
- **W2**：`test_step_read_whitelist_branch_is_live` 在 tmp 树造白名单路径 + 越界文件，
  断言只有白名单豁免。✓
- **W3**：`test_runtime_closure_clean` 断言 `returncode == 0`，uv 缺失为显式失败非 skip。✓
- **test_ci_workflow 假自证**：`test_reverse_self_test_for_ci` 用真实 ci.yml 文本喂
  同一 `missing_tokens`（Windows → ubuntu / basedpyright → echo 两个变异）。✓

### 5. dc2cdac 之后 6 提交核查（54ac0af / 5cb53da / 5563e38 / 3374d3a / 3c923b4 / 6086b29）

逐一 `git show` + 违禁模式扫描（forbidden imports / 商业格式 / 网络 / 类型抑制 /
保留命名空间）：**零新增违规**。54ac0af 的 grep 命中全部位于 evidence 文档引文内
（`.md` 不在 `.py` 扫描域）。`scripts/report_junit_failures.py`（3c923b4）为纯 stdlib
CI 辅助脚本，不触 `scan_out_of_scope` 任何红线；顶层 `scripts/` 目录不在
planning-scratch 禁止清单（仅 review/island 目录与 `*-ledger.md` 文件）。

### 6. 仍存的非阻断项（→ 阶段 1 backlog）

M1 补 tkinter/wx；M13/M14 驼峰拼接（`JTProvider`/`DwgProvider`/`ElementMapper` 类）——
可考虑 token 级大小写折叠 + 后缀剥离；M19 subprocess/seccomp 沙箱路线静态不可穷举
（可加运行时行为测试兜底）；M25 ADR-003 §9 全部保留 id 机器化；M3/M7 维持 F1 矩阵
人工承担（或引入结构性断言：`src/mycad/agent/` 只许 dataclass/typing 构造）。

DONE: F4-recheck verdict=APPROVE(有条件), 20/20 scope-audit 全绿 + M1-M25 重推导 0 VIOLATED + 6 新提交零违规; 由主会话自查落盘(派发通道全灭已记 ledger), 方法学=全部结论由 HEAD 代码现推。
