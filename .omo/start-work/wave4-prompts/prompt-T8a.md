# T8a：formats 包 src 侧 + geom io 接线 + 单元测试

你的第一动作已完成（正在读本文件）。按 §6 清单逐步执行。**禁把本清单另存为文件。**

## 1. 任务
新建 `src/mycad/formats/` 包（base.py / registry.py / providers/）+ `src/mycad/geom/io.py` 接线（替换 kernel 两处 NotImplemented 占位）+ `tests/formats/` 单元测试。全部用 `.venv/bin/python`、`.venv/bin/ruff`、`.venv/bin/basedpyright`（工作目录=仓库根）。

## 2. 步骤 0：取回权威规格（必做）
```
sed -n '380,402p' .omo/plans/phase0-mvp.md
```
逐字过目。本文件与计划冲突时以计划为准；发现冲突→在 DoneClaim deviations 记录并按计划执行。

## 3. 白名单（只允许创建/修改以下文件，其余只读；禁 git 操作）
- 新建：`src/mycad/formats/__init__.py`、`src/mycad/formats/base.py`、`src/mycad/formats/registry.py`、`src/mycad/formats/providers/__init__.py`、`src/mycad/formats/providers/step_provider.py`、`src/mycad/formats/providers/stl_provider.py`
- 新建：`src/mycad/geom/io.py`
- 修改：`src/mycad/geom/kernel.py` —— **仅允许**把 `export_step`/`export_stl` 两处 `raise NotImplementedError` 占位方法体替换为 io 委托（docstring 同步改），文件其余字节禁改
- 新建：`tests/formats/__init__.py`、`tests/formats/test_base.py`、`tests/formats/test_registry.py`

## 4. 依赖面事实（已核实，勿重复勘察）
- `mycad.core.ports`：`ExportableKernel`（reset/apply/mass_properties/export_step/export_stl）、`FormatPort`（name/vendor/priority/extensions/can_write 属性 + write 方法，@runtime_checkable）、`FormatResolver`（resolve(path)->FormatPort）。
- `mycad.core.exceptions`：`EmptyGeometryError`、`UnknownFormatError`（纯 message+command_id）；`ProviderConflictError(extension: str="", provider1: tuple[str,str]=("",""), provider2: tuple[str,str]=("",""))`。
- build123d 顶层有 `export_step`、`export_stl`、`import_step`（本片只用前两个；import_step 禁止出现在 src）。
- kernel.py 第 120/125 行起是两个占位方法；kernel 内部几何状态变量名与空态表示先读 kernel.py 确认（A0）。
- formats 包**禁 import build123d/OCP/geom**（只许 import mycad.core.* 与标准库）；build123d 调用全部在 geom/io.py 内。
- 每个 .py 文件头两行 SPDX（照抄 `src/mycad/core/ports.py` 的两行格式）。

## 5. 钉死设计（执行者零发明）
- **base.py**：`class ImportKind(str, enum.Enum)` 三成员 DUMB_SOLID/"dumb_solid"、ASSEMBLY_WITH_ATTRS/"assembly_with_attrs"、EDITABLE_FEATURES/"editable_features"（阶段 0 仅为词汇表定义，无任何返回路径）。`@dataclass(frozen=True) class FormatProvider` 字段**恰八个按序**：name: str、vendor: str、priority: int、extensions: tuple[str, ...]、can_read: bool、can_write: bool、target: Literal["shape","xcaf"]、_writer: Callable[[ExportableKernel, Path], None]；方法 `def write(self, geometry: ExportableKernel, path: Path) -> None: self._writer(geometry, path)`（实现 T6 FormatPort；禁模块级 write 函数、禁 params 参数）。
- **registry.py**：`class FormatProviderRegistry`，`__init__(self, providers: Iterable[FormatProvider] = ())` 逐个 register；`register(provider)`：对每个已注册 provider，若扩展名集合相交**且 priority 相等**→ 抛 ProviderConflictError（extension=排序后第一个相交扩展名，provider1=(已注册.name, 已注册.vendor)，provider2=(新.name, 新.vendor)，消息含扩展名与两组 name/vendor）；否则 append。`get_by_extension(ext: str)`：规范化（小写、确保前导点）→ 候选为 extensions 含该扩展名者；空→`UnknownFormatError(f"no registered provider handles {norm!r}")`（**消息不得含 "support" 字样**——不承诺支持）；非空→`min(candidates, key=priority)`。`list_providers() -> tuple[FormatProvider, ...]`（注册序）。`resolve(path: Path) -> FormatPort`（返回类型标注 FormatPort；实现=path.suffix.lower() 走 get_by_extension）。
- **providers**：`step_provider.py` 定义模块级 `_write_step(geometry, path)`（函数体一行 `geometry.export_step(path)`）+ 常量 `STEP_PROVIDER = FormatProvider(name="STEP", vendor="OCC", priority=100, extensions=(".step",), can_read=False, can_write=True, target="shape", _writer=_write_step)`。`stl_provider.py` 对称（name="STL"，extensions=(".stl",)，`geometry.export_stl(path)`）。extensions 钉死单元素元组（".step",)/(".stl",)——偏离记录 D1。
- **`src/mycad/formats/__init__.py`**：再导出 FormatProvider、FormatProviderRegistry、ImportKind、STEP_PROVIDER、STL_PROVIDER。
- **geom/io.py**：`write_step(part, path)`/`write_stl(part, path)` 两函数；part 为空态（A0 确认判据：`_part is None` 或等价）→ 抛 EmptyGeometryError（消息含 "empty"；不写出任何文件——检查在调用 build123d 之前）；否则调 build123d export_step/export_stl。part 参数类型注解与 kernel 内部状态类型一致（A0 读 kernel.py 确定）。
- **kernel.py 占位替换**：
  ```python
  def export_step(self, path: str | Path) -> None:
      """Write the current model as a STEP file (wired by T8 via geom.io)."""
      write_step(self._part, Path(path))
  ```
  export_stl 对称。顶部 import `from mycad.geom.io import write_step, write_stl`。
- **test_base.py**（≤130 行）：①STEP/STL 常量逐字段锁定（name/vendor/priority=100/extensions/can_read=False/can_write=True/target="shape"）；②`isinstance(STEP_PROVIDER, FormatPort)` 且 hasattr 核心属性；③fake writer 注入：FormatProvider(..., _writer=recorder).write(fake, p) → recorder 收到 (fake, p)；④ImportKind 三成员存在；⑤空几何（真 BuildKernel() 新建、零命令）：parametrize step/stl → pytest.raises(EmptyGeometryError) 且目标文件不存在（`from mycad.geom.kernel import BuildKernel` 合法）。
- **test_registry.py**（≤170 行）：①注册后 get_by_extension(".step") is STEP_PROVIDER（".stp" 无、抛 UnknownFormatError）；②未知扩展 ".x_t"/".dwg" 参数化 → UnknownFormatError 且消息含扩展名、`"support" not in str(exc).lower()`；③priority 选择：注册伪 provider priority=50 extensions=(".step",) → get_by_extension(".step") is 伪；④同 priority 同扩展名冲突 → ProviderConflictError，断言 e.extension==".step"、e.provider1/e.provider2 两组 (name,vendor)（用自定义 name 便于断言）；⑤同 priority 不相交扩展名不冲突；⑥list_providers 注册序；⑦`isinstance(registry.resolve(tmp_path/"f.step"), FormatPort)`；⑧端到端：真 BuildKernel+apply 一条 feature.box（参数形状 A0 从 _b123_ops.py 确认）→ resolve(".step").write(kernel, tmp/"f.step") 文件存在且 >0 字节；".stl" 同理。
- **反停摆五纪律**：禁写清单文件；单文件写 ≤120 行（cat > / cat >> 分批）；每回合恰好一个小动作并落盘；禁长内部推理（直接干活）；被阻塞即停并在尾消息写 BLOCKED+原因。
- **basedpyright strict 零 ignore**；ruff（E/F/W/I/B/UP/C4）零豁免（函数内 import 允许，无 PLC0415）。

## 6. 清单（每步一回合）
- A0：读参考——`sed -n '380,402p' .omo/plans/phase0-mvp.md`；cat src/mycad/core/ports.py、src/mycad/core/exceptions.py 相关段；sed -n '1,135p' src/mycad/geom/kernel.py（内部状态+占位+import 区）；`.venv/bin/python -c "import build123d, inspect; print(inspect.signature(build123d.export_step)); print(inspect.signature(build123d.export_stl))"`；grep -n "def apply_primitive" -A 25 src/mycad/geom/_b123_ops.py（box 参数形状）。
- A1：写 src/mycad/geom/io.py（cat >，一次成文 ≤60 行）。
- A2：edit kernel.py 两占位为 io 委托 + 顶部 import（一次 edit 调用含两处替换与 import 行）。
- A3：冒烟（不落测试）：`.venv/bin/python -c` 建真核 apply 一条 box，export_step 到 /tmp/opencode/t8a-smoke.step 与 .stl，断言文件 >0 字节；再空核 export → 预期 EmptyGeometryError 打印确认。
- A4：写 src/mycad/formats/base.py。
- A5：写 providers 三件（__init__ 再导出两 provider）。
- A6：写 src/mycad/formats/registry.py。
- A7：写 src/mycad/formats/__init__.py。
- A8：写 tests/formats/__init__.py + test_base.py（一次 cat >，≤130 行）。
- A9：写 tests/formats/test_registry.py（≤170 行）。
- A10：scoped 终验（全部必须绿，输出原样贴尾消息）：
  - `.venv/bin/python -m pytest tests/formats tests/test_layering.py -q`
  - `.venv/bin/basedpyright src/mycad/formats src/mycad/geom/io.py src/mycad/geom/kernel.py tests/formats`
  - `.venv/bin/ruff check src/mycad/formats src/mycad/geom/io.py src/mycad/geom/kernel.py tests/formats && .venv/bin/ruff format --check src/mycad/formats src/mycad/geom/io.py tests/formats`
- A11：尾消息输出 DoneClaim JSON（见下）。

## 7. DoneClaim 格式（尾消息，JSON 代码块）
```json
{"task": "T8a", "status": "DONE",
 "files": ["<每个新建/修改文件+行数>"],
 "tests": {"pytest": "<A10 第一条输出的末行摘要>", "pyright": "<errors 数>", "ruff": "clean|N"},
 "smoke": "<A3 冒烟结果一句话>",
 "deviations": ["D1: extensions 钉死单元素（规格未枚举）", "..."]}
```
