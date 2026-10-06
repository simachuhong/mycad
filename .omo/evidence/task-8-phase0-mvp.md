# Task 8 — FormatProvider 注册表与 STEP/STL 写 provider（Phase-0 MVP）

## §T8a formats 片（编排方采信，2026-10-06）

实例 ses_eef40a454ffe2IeovZApWPOqIu 于 A10 终验回合静默死亡（18:40:53 后 30min 无消息，
配额墙/停摆模式，与 T6b 同型）。A1-A9 全部交付物已落盘，DoneClaim 缺失，按 a1/T6b 先例
由编排方完成 A10 终验并采信。

### 编排方验收（三要素）
- 磁盘交付：formats/{__init__,base,registry}.py + providers/{__init__,step_provider,stl_provider}.py
  + geom/io.py + kernel.py 两占位替换 + tests/formats/{__init__,test_base,test_registry}.py（15 例）。
- scoped 四门复跑：pytest tests/formats+test_layering **21 passed** / basedpyright 点名 0/0/0 /
  ruff check+format clean。
- 冒烟复跑（A3 等效）：真核 box → STEP 16990B / STL 684B；空核 export_step → EmptyGeometryError。
- 规格审阅：registry 同优先级扩展重叠→ProviderConflictError(extension, provider1, provider2)；
  解析取最小 priority；未知扩展→UnknownFormatError；resolve() 经 cast 桥接 FormatPort；
  FormatProvider frozen+注入 _writer 闭包（formats 包零 build123d import）；io.py None→
  EmptyGeometryError 先于 I/O；STEP/STL_PROVIDER 字段钉死（priority=100, can_read=False,
  can_write=True, target="shape"）。

### 偏离记录
- D1: extensions 钉死单元素 (".step",)/(".stl",)——规格未枚举 .stp 等别名，Phase 0 不扩展。
- D2: kernel.py export_step/export_stl 签名保留 `path: str | Path`（T6 端口契约），内部 Path(path) 规范化。
- D3: base.py 定义 ImportKind 三值词汇表（dumb_solid/assembly_with_attrs/editable_features）——
  规格「Phase 0 定义分级词汇，无任何 provider 返回 editable_features」；测试含反向守卫。

## §T8b STEP 读回 + golden 法兰 QA + 守卫（编排方接管收尾，2026-10-06）

实例 ses_eef10b664ffeflAW5idrjAUvBU 于 B3 中途死于 5h 配额墙（19:20:25 后静默，
尾消息无 DoneClaim；与主编排同一中断事件）。B1-B2 及 B3 第一批已落盘；
B3 第二批/B4/B5/B6 由编排方按 prompt-T8b.md §5 钉死规格接管完成。

### 交付物（编排方接管部分）
- tests/formats/test_export_roundtrip.py 补齐第二批（中文路径/未知格式/空几何/同优先级冲突，156L 终态）。
- tests/formats/test_guards.py 新建（4 守卫：STEP 读 API 唯一位置+src 零出现/formats src 零 CAD import/
  formats 测试零组合根符号/EDITABLE_FEATURES 唯枚举定义处）。
- tests/helpers/step_roundtrip.py 修复 basedpyright strict（import 绑定改模块属性+cast，镜像 geom/io.py 模式）。

### 8 id 列表
不适用：本片无命令接线（T8 只交付格式 provider；命令面在 T7）。

### golden 法兰（T11 权威参数）
1. feature.cylinder {radius:40.0, height:8.0, center:[0,0,0], mode:new}
2. feature.hole {target_face:{surface:plane,axis:+Z,rank:0}, position:{kind:center},
   diameter:20.0, depth:{kind:through_all}}
3. feature.hole_pattern {base_hole:<同 2 形状 diameter:6.0>, pattern:{kind:polar,radius:25.0,count:4,start_angle_deg:0.0}}

### 实测（.venv/bin/python，临时目录）
- 几何 golden：volume=36794.3331588436 vs 期望 36794.3331588437，delta=1.455e-11；solid_count=1。
- STEP 字节数 24507（>10240 ✓）；STL 字节数 152084（>1024 ✓）。
- STEP 读回：solids=1，volume=36794.3331588451，delta=1.419e-09（<1e-6 ✓）。
- 中文路径（目录/flange_法兰.step）：写出+读回 solids=1，delta=1.419e-09 ✓。

### failure 场景（逐字输出）
- .x_t → UnknownFormatError: no registered provider handles '.x_t'（消息无 "support" 字样 ✓）
- .dwg → UnknownFormatError: no registered provider handles '.dwg'
- 空核 → EmptyGeometryError: STEP export to .../e.step refused: the model is empty（文件未创建 ✓）
- 同优先级 .step 双 provider → ProviderConflictError(extension=".step", provider1=("Alpha","VendorA"), provider2=("Beta","VendorB"))

### 偏离记录（T8b 侧）
- D4: 子代理 B2 docstring 含 "no AppServices, no build_app" 字面量违反守卫 → 编排方改写为
  "no composition-root symbols"（守卫禁的是符号引用，语义不变）。
- D5: step_roundtrip.py `from build123d import import_step` 绑定本身触发
  reportUnknownVariableType → 改 `import build123d` + cast(Callable[[Path], Compound], build123d.import_step)
  （镜像 io.py 既有模式；非 suppression）。
- D6: test_export_roundtrip.py import 块 I001 → ruff --fix 自动排序（STEP_PROVIDER/STL_PROVIDER 前置）。
- D7: 守卫文件文本针全部拼接构造（"import"+"_step" 等），防自引用误报。

### 验收命令与结果（scoped，2026-10-06）
- .venv/bin/python -m pytest tests/formats tests/helpers tests/test_layering.py tests/test_core_isolation.py -q
  → **34 passed**
- .venv/bin/basedpyright tests/helpers tests/formats/test_export_roundtrip.py tests/formats/test_guards.py
  → **0 errors, 0 warnings, 0 notes**
- .venv/bin/ruff check + format --check 同路径 → clean / 7 files already formatted
- D8: tests/geom/test_kernel_primitives.py::test_export_step_and_stl_are_placeholders 为
  T2 时代占位断言（NotImplementedError），被 T8a 真实现作废；T8a scoped 门（tests/formats+
  test_layering）未覆盖 tests/geom 致漏网，全量门暴露。改写为
  test_export_step_and_stl_reject_empty_model（空核 → EmptyGeometryError，新契约）。
