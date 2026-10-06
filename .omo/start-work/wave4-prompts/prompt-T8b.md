# T8b：STEP 读回辅助 + golden 法兰导出 QA + 守卫测试 + evidence

你的第一动作已完成（正在读本文件）。按 §6 清单逐步执行。**禁把本清单另存为文件。**

## 1. 任务
新建 `tests/helpers/step_roundtrip.py`（tests 中唯一 build123d 读 API 位置）+ `tests/formats/test_export_roundtrip.py`（golden 法兰端到端）+ `tests/formats/test_guards.py`（守卫断言）+ `.omo/evidence/task-8-phase0-mvp.md`。前提：T8a 已交付 formats src 与 geom io 接线。

## 2. 步骤 0：取回权威规格（必做）
```
sed -n '380,402p' .omo/plans/phase0-mvp.md
```
逐字过目，尤其是测试段与 QA scenarios 段。冲突以计划为准并记 deviations。

## 3. 白名单（只允许创建以下文件，其余只读；禁 git 操作）
- 新建：`tests/helpers/__init__.py`、`tests/helpers/step_roundtrip.py`
- 新建：`tests/formats/test_export_roundtrip.py`、`tests/formats/test_guards.py`
- 新建：`.omo/evidence/task-8-phase0-mvp.md`
- **只读**：src/mycad/formats/**、src/mycad/geom/**（含 io.py、kernel.py）、src/mycad/core/**、tests/ 全部现有文件

## 4. 依赖面事实（已核实）
- formats 公开面：`from mycad.formats import FormatProvider, FormatProviderRegistry, ImportKind, STEP_PROVIDER, STL_PROVIDER`。
- ProviderConflictError(extension, provider1, provider2)；UnknownFormatError；EmptyGeometryError 均在 mycad.core.exceptions。
- `mycad.geom.kernel.BuildKernel`：`apply(command_id, params)` / `mass_properties() -> MassProperties`（volume/solid_count 字段）/ `export_step` / `export_stl`。
- **golden 法兰序列**（T11 权威参数，QA happy path 逐字用）：
  1. `feature.cylinder`：`{"radius": 40.0, "height": 8.0, "center": [0.0, 0.0, 0.0], "mode": "new"}`
  2. `feature.hole`：`{"target_face": {"surface": "plane", "axis": "+Z", "rank": 0}, "position": {"kind": "center"}, "diameter": 20.0, "depth": {"kind": "through_all"}}`
  3. `feature.hole_pattern`：`{"base_hole": {<与 2 相同的 target_face/position 形状>, "diameter": 6.0, "depth": {"kind": "through_all"}}, "pattern": {"kind": "polar", "radius": 25.0, "count": 4, "start_angle_deg": 0.0}}`
  - **参数形状以 src/mycad/geom/_b123_features.py 的 _hole/_hole_pattern 实现为准**（A0 先读；若与本提示词有出入，源码赢，记 deviation）。
  - 期望体积 = `math.pi * 8 * (40**2 - 10**2 - 4 * 3**2)` = 36794.3331588437（容差 1e-6）；solid_count == 1。
- STEP>10240 字节；STL>1024 字节；STEP 读回体积 1e-6 一致。
- tests 是包（tests/__init__.py 存在）→ 导入用 `from tests.helpers.step_roundtrip import ...`。
- QA 纪律：**测试源码不得出现 AppServices/build_app/new_document**（T8 在 T7 之前，只许用 T2/T5/T6/T8a 已交付符号）。

## 5. 钉死设计
- **tests/helpers/step_roundtrip.py**（≤50 行）：`from build123d import import_step`（tests 全树唯一 build123d **读 API** import）；提供 `read_step(path) -> tuple[int, float]`（solid 数、体积 mm³）。import_step 返回形态 A0 探明（可能返回对象或元组；体积用 mass properties 或 API 等价物）。**src 中禁止出现 import_step**。
- **test_export_roundtrip.py**（≤220 行，分两批 cat >>）：
  - fixture `flange_kernel()`：BuildKernel + 上述三命令 apply，返回 kernel；先断言 `abs(mp.volume - expected) < 1e-6` 且 solid_count==1（几何本身 golden）。
  - `test_flange_step_roundtrip`：registry = FormatProviderRegistry([STEP_PROVIDER, STL_PROVIDER])；port = registry.resolve(tmp_path/"flange.step")；port.write(kernel, ...)；文件 >10240 字节；solids, vol = read_step(...)；solids==1 且 abs(vol-expected)<1e-6。
  - `test_flange_stl_export`：resolve(".stl") 写出 >1024 字节（STL 不读回）。
  - `test_chinese_path`：`tmp_path/"目录"/"flange_法兰.step"`（mkdir parents=True）写出+读回体积一致。
  - `test_unknown_format_rejected`：".x_t"/".dwg" 参数化 → UnknownFormatError，`"support" not in str(exc).lower()`。
  - `test_empty_export_rejected`：空 BuildKernel → resolve 写出 → EmptyGeometryError 且文件不存在（step/stl 参数化）。
  - `test_same_priority_conflict`：两个 priority=100 的 ".step" 伪 provider → ProviderConflictError，断言 extension/两组 (name,vendor)。
  - 路径一律 pathlib+tmp_path，禁字符串 "/" 拼接（Windows CI 兼容）。
- **test_guards.py**（≤140 行）：
  - `test_step_read_api_only_in_helper`：扫描 tests/**/*.py（跳过 __pycache__）文本中 "import_step" 出现位置 ⊆ {tests/helpers/step_roundtrip.py}；扫描 src/**/*.py 零出现。
  - `test_formats_src_no_cad_imports`：ast.walk 扫 src/mycad/formats/**/*.py，无 build123d/OCP import。
  - `test_formats_tests_no_app_symbols`：tests/formats/*.py 文本不含 "AppServices"/"build_app"/"new_document"。
  - `test_no_editable_features_return_path`：src/**/*.py 中 "EDITABLE_FEATURES" 出现位置 ⊆ {src/mycad/formats/base.py}（枚举定义处；无返回路径）。
- **evidence**（.omo/evidence/task-8-phase0-mvp.md，§T8 段）：8 项内容——8 id 不适用说明（本片无命令）、golden 法兰三命令参数、STEP/STL 实测字节数、读回体积与期望差、中文路径结果、三个 failure 场景输出、deviations（含 T8a 侧 D1 extensions 钉死——向编排方声明即可）、验收命令与结果。
- **反停摆五纪律**（同 T8a）：禁写清单文件；单文件 ≤120 行分批；每回合一个小动作落盘；禁长推理；BLOCKED 即止。

## 6. 清单（每步一回合）
- B0：`sed -n '380,402p' .omo/plans/phase0-mvp.md`；读 src/mycad/formats/ 全部 + src/mycad/geom/io.py + `grep -n "def _hole\b" -A 50 src/mycad/geom/_b123_features.py` 与 `_hole_pattern` 段 + `.venv/bin/python -c "import build123d, inspect; print(inspect.signature(build123d.import_step))"`；确认 tests/ 无既有 import_step 出现（grep）。
- B1：写 tests/helpers/__init__.py + step_roundtrip.py。
- B2：写 test_export_roundtrip.py 第一批（fixture+STEP/STL 两测试）。
- B3：写 test_export_roundtrip.py 第二批（中文路径/未知格式/空几何/冲突）。
- B4：写 test_guards.py。
- B5：scoped 终验（贴尾消息）：
  - `.venv/bin/python -m pytest tests/formats tests/test_layering.py tests/test_core_isolation.py -q`
  - `.venv/bin/ruff check tests/helpers tests/formats/test_export_roundtrip.py tests/formats/test_guards.py && .venv/bin/ruff format --check tests/helpers tests/formats/test_export_roundtrip.py tests/formats/test_guards.py`
  - `.venv/bin/basedpyright tests/helpers tests/formats/test_export_roundtrip.py tests/formats/test_guards.py`
  - 采集字节数：`ls -l` 产物由测试内 tmp 产生——改为在 B2 测试运行输出里打印（pytest -s 一次）或临时脚本量测后写入 evidence。
- B6：写 .omo/evidence/task-8-phase0-mvp.md（§T8）。
- B7：尾消息 DoneClaim JSON：`{"task":"T8b","status":"DONE","files":[...+行数],"tests":{"pytest":"...","ruff":"clean","pyright":"0 errors"},"evidence":"<路径>","deviations":[...]}`。

## 7. 硬禁令
- 禁实现任何 STEP 读产品路径（src 零 import_step）；禁 IGES/glTF/BREP/3MF/DXF；禁碰商业格式；禁把导出写进命令历史；禁 AppServices/build_app/new_document 出现于任何新文件。
