# T6d 任务书：persistence + schema_v1 + migrations + core/__init__ + 隔离/集成/性能门（T6 收官波）

你是 MyCAD 项目的实现代理。本文件是你的完整任务书。禁止写任何计划/清单/分析文件——
本文件就是全部清单，从 D0 顺序机械执行，每完成一步输出 `DONE D<n>`。

## 0. 启动纪律（反停摆五纪律，违反=任务失败）
- 禁止写任何"计划/清单/思考"文件；单次文件写入 ≤150 行（cat > 新文件 / cat >> 追加分块）。
- 每回合恰好完成清单一个小步并落盘；禁止一回合内做多步。
- 禁止长推理：动手前不写长段分析；规格存疑时用 `sed -n '<行号>p' .omo/plans/phase0-mvp.md` 取原文对照，不凭记忆。
- BLOCKED（依赖缺失/测试无法转绿且 2 次修复失败）→ 立即停止，会话尾输出 DoneClaim 标 `"blocked": true` 与原因，不绕路。
- 全程禁止 git 操作（add/commit/push/checkout 等）。

## 1. 交付物白名单（只许创建/修改这些文件，其余一律禁碰）
新建：
- `src/mycad/core/__init__.py`（import 全部 core 子模块并 re-export——隔离测试的牙齿）
- `src/mycad/core/persistence.py`
- `src/mycad/core/schema_v1.py`
- `src/mycad/core/migrations/__init__.py`
- `tests/core/test_persistence.py`
- `tests/core/test_core_integration.py`
- `tests/test_core_isolation.py`（**tests 根目录，不在 tests/core/**）
修改（授权最小扩展，仅此一处）：
- `src/mycad/core/exceptions.py`：仅 `ArchiveVersionError` 追加两个带默认值字段 `found: str = ""` 与 `supported: str | int = ""`（+docstring 注明 #round9-NB-E 字段填充规则）。tests/test_exceptions.py 只锁 15 类名单与特定字段，不受影响——改后必须复跑它。
追加：
- `.omo/evidence/task-6-phase0-mvp.md`（追加 `## T6d` 段；若文件不存在则创建含 `# T6 证据` 头；**不动其他段落**）
禁改：document.py/bus.py/plan.py/signals.py/groups.py/selectors.py/geometry_types.py/kernel_protocol.py/handlers.py/ports.py/exceptions.py 其余部分、tests/core 现有全部测试、src/mycad/geom、src/mycad/commands。

## 2. 上游 API 发现（D0 第一动作，cat 只读；序列化访问器以此为准，禁止臆造）
- `src/mycad/core/document.py`（Document 公开访问器、ExecutedCommand 六字段+amendments、metadata API、组 API）
- `src/mycad/core/bus.py`（CommandBus 构造签名、execute、_rebuild）
- `src/mycad/core/groups.py signals.py selectors.py plan.py exceptions.py kernel_protocol.py handlers.py ports.py`
- `src/mycad/commands/registry.py validation.py`（registry.get/schema_defs；validate_params/normalize_params 签名）
- `src/mycad/geom/kernel.py`（BuildKernel: reset/apply/mass_properties）+ `tests/geom/_geometry.py`（真核夹具形态）
- `sed -n '325,352p' .omo/plans/phase0-mvp.md`（T6 规格 persistence/测试/QA 段原文）
- `sed -n '550,600p' .omo/plans/phase0-mvp.md`（附录 A.0 选择器 JSON 形态）

## 3. 规格（权威摘录；冲突时以计划原文为准）
- 存档 JSON：UTF-8、ensure_ascii=False、indent=2、键序稳定：
  `{"format":"mycad.document","version":1,"metadata":{...},"commands":[{"id","version","params","ordinal","timestamp_utc","confirmed_by",("amendments" 仅非空时出现)}],"named_groups":[{"name","faces":[<FaceSelector JSON>],"edges":[<EdgeSelector JSON>]}]}`
- **wire 规则（#round8-2/#round9-3）**：选择器 axis/curve/rank 为 None 时 JSON 中**省略该键，绝不写 null**；空列表显式写出；named_groups 元素恰三键。存档出现显式 `"axis": null`（或 curve/rank null）属损坏数据→ValidationError（reason 指向该选择器）。
- save 契约：`save_document(document: Document, path: Path) -> None`——原子写（同目录临时文件+os.replace）；写前发 document_saving、写后发 document_saved；父目录不存在 OSError 透传（不自动创建）。
- open 契约：`open_document(path: Path, *, registry: CommandRegistry, kernel: Kernel, handlers: Mapping[str, CommandHandler]) -> LoadedDocument`；`LoadedDocument(document: Document, bus: CommandBus)`（frozen dataclass）。open 恢复数据后**自动整体 _rebuild() 一次**（重放不改写任何原 timestamp/ordinal/confirmed_by/amendments）；bus 以注入的 registry/kernel/handlers 装配（open_document 不单独接收 defs）。
- 打开异常映射（闭合 15 类，禁新增）：①JSON 损坏/顶层非对象/缺顶层键/命令元素缺六字段/类型错/未知 metadata 键/未知顶层键→**ValidationError**（reason 注明 JSON 指针路径）；②format≠"mycad.document" 或 version≠1→**ArchiveVersionError**：format 不符 `found`=实际串（缺失=占位 "missing"）、`supported="mycad.document"`；version 不符 `found`=str(version)（如 "99"）、`supported=1`——两场景分别 assert 两组字段；③命令 id 无处理器→**UnknownCommandError**（identifier=id，消息含 ordinal 与 id）；④重放几何失败→GeometryBuildError/TopologyReferenceError 原样带 ordinal 透传。文件不存在不处理（OCP/CLI 层职责，open() 自然抛）。
- migrations：`Migration(from_version, to_version, fn)` 注册表；v1 无条目；单测证明未知版本路径报错文案正确。
- 隔离测试：`tests/test_core_isolation.py` **必须 subprocess.run([sys.executable,"-c",...]) 全新子进程**断言：import mycad.core 后 `"build123d" not in sys.modules and "OCP" not in sys.modules`；反向自证 import mycad.geom 后两者确实出现。禁止主 pytest 进程内查 sys.modules。
- 性能门（NF-04）：≤10 命令 box/cylinder 序列整体重放 10 次，每次墙钟 **< 1000ms 断言**（超时即失败）。
- Must NOT do：不 import geom/formats（persistence 只持 core 内类型与 Protocol）；不做 BREP 内嵌/快照缓存；单线程文档模型（docstring 注明）。

## 4. 编排方钉死的设计（唯一自由度已收敛）
### 4.1 import 纪律（防包级循环导入，最高优先级）
commands/spec.py、registry.py 顶层 import `mycad.core.exceptions`；你创建的 `core/__init__.py` 会 import 全部 core 子模块。因此 **persistence.py/schema_v1.py/migrations 顶层禁止 import 任何 mycad.commands 模块**（persistence 实际完全不需要 commands：registry/handlers/kernel 均以实例传入，类型用 core 内 Protocol/类注解）。`core/__init__.py` 的 import 顺序固定：exceptions → selectors → geometry_types → signals → groups → kernel_protocol → handlers → ports → plan → document → bus → migrations → persistence（依赖先于依赖者）。每行 `from .x import ...` + 末尾 `__all__`。
### 4.2 schema_v1.py（手写结构校验，不依赖 T3 校验器递归）
- 常量：`ARCHIVE_FORMAT = "mycad.document"`、`ARCHIVE_VERSION = 1`。
- `validate_archive(data) -> None`（坏则抛 ValidationError，reason 含 JSON 指针）：顶层恰五键 format/version/metadata/commands/named_groups（未知键/缺键/类型错均拒）；metadata 恰六白名单键（与 document.METADATA_KEYS 一致，值全 str）；commands 元素恰六键+可选 amendments（id/version/params/ordinal/timestamp_utc/confirmed_by 类型逐项检查；amendments 为数组且元素含 at/actor/from_params/reason）；named_groups 元素恰三键 name/faces/edges，faces/edges 为数组。
- **null 扫描**：递归扫描每个 command 的 params 与 named_groups 的 faces/edges，键 "axis"/"curve"/"rank" 值为 None → ValidationError（reason 如 `commands/0/params/target_face/axis: explicit null violates wire rule (omit the key)`）。
- `selector_from_json(d, pointer) -> FaceSelector | EdgeSelector`：surface=plane→axis 必填六轴值之一、rank 可选 int≥0；surface=cylinder→axis 可缺（存在则六轴值）、rank 可选；EdgeSelector→parent_faces 数组（minItems 1）逐个转 FaceSelector、curve 可缺（存在则 "line"/"circle"）；选择器对象未知键→ValidationError（additionalProperties:false 语义）。
### 4.3 persistence.py
- `save_document`：`document.events.emit("document_saving", {"path": str(path)})` → 构造 dict（命令六字段+amendments 非空才写；named_groups 三键，faces/edges 逐选择器序列化：None 键省略；空组列表显式 `[]`）→ `json.dumps(..., ensure_ascii=False, indent=2)` → 同目录 `tempfile.NamedTemporaryFile("w", suffix=".tmp", delete=False, dir=path.parent, encoding="utf-8")` 写入+flush+os.replace → `emit("document_saved", {"path": str(path)})`。metadata 取 document 快照 API（D0 确认名称）。
- `open_document` 流水线（顺序固定）：`path.read_text(encoding="utf-8")`（OSError 自然抛）→ `json.loads`（JSONDecodeError→ValidationError 含位置）→ format 检查→version 检查（ArchiveVersionError 按上述字段规则；先 format 后 version）→ `migrations.migrate(data)`（v1 恒等）→ `validate_archive` → 逐命令预检：`registry.get(cmd.id, cmd.version)` 缺→UnknownCommandError（identifier=id，消息含 ordinal）；`handlers.get(id)` 缺→UnknownCommandError（同）——预检先于任何 Document 构造 → 构造 Document（metadata=、commands=[ExecutedCommand(...) 逐条重建]、named_groups=经 selector_from_json 转换）→ `CommandBus(document, registry, kernel, handlers)` → `bus._rebuild()` 一次（捕获后原样透传，异常时 LoadedDocument 不产生=无部分构造）→ `LoadedDocument(document, bus)`。
### 4.4 migrations/__init__.py
`@dataclass(frozen=True) class Migration: from_version: int; to_version: int; fn: Callable[[dict[str, Any]], dict[str, Any]]`；模块级 `_REGISTRY: list[Migration]` + `register(m)`；`migrate(data, *, supported_version=ARCHIVE_VERSION)`：`data["version"]==supported` → 原样返回；否则查链，无链→`ValueError`（消息含发现的 version 与已注册迁移数——单测锁文案含版本数字）。出厂 `_REGISTRY` 为空。
### 4.5 测试矩阵
- test_persistence.py（≤380 行，≥4 批 cat）：migrations registry（注册 1→2 后链可用；未注册版本 3→ValueError 文案含 "3"；v1 恒等）；异常矩阵（malformed JSON/未知 metadata 键且无部分构造/未知顶层键/缺 handler 含 ordinal 与 id/FakeKernel 第 2 条失败→GeometryBuildError ordinal==1/version=99→ArchiveVersionError(found=="99", supported==1)/format 篡改→(found==实际串, supported=="mycad.document")/缺 format→found=="missing"/显式 "axis":null 与 "rank":null 篡改→ValidationError）；往返矩阵（六字段+空/非空 amendments 完整恢复、timestamp 字符串相等、NamedGroup 两组混合 selector 逐字段相等、remove 后存档键消失、cylinder 无 axis 命令 save 后 raw json `"axis" not in raw`、EdgeSelector 无 curve 往返、空组显式 []、amendments 空则键不现、document_saving/saved 各恰一次含 path payload、父目录不存在 pytest.raises(OSError)、save 后目录无 .tmp 残留）。FakeKernel/FakeHandler/EchoHandler 自造（同 test_bus.py 形态）。
- test_core_integration.py（≤300 行，≥3 批）：自建 CommandSpec（feature.box size_x/y/z Positive required；feature.cylinder radius/height Positive、center 默认 [0,0,0]、mode enum 默认 new；modify.fillet radius Positive+edges 数组——形态从 tests/geom 夹具取）+ BuiltinModelingHandler + 真 BuildKernel。①execute box+cylinder(add) →undo(2)→体积==box 解析值→redo→体积==组合值；②edit_and_replay cylinder radius 2→3 体积 πr²h 解析值；③QA happy path：三命令→undo2→redo→save tmp_path/"out.mc.json"→新装配 open→体积一致+六字段完整；④真核批回滚两场景（step2 validate 失败 radius=-1.0；step3 几何失败——D13 前置实验选定：优先 modify.fillet 超大半径 on 10mm box，python -c 实证抛 GeometryBuildError，不抛则换 boolean_cut 空工具体直至找到，选型记录进 evidence）：历史无批命令、体积回批前、BatchRollbackError 四字段、plan.status=="failed"；⑤性能门：10 命令 box/cylinder 序列存档后 10 次 `open_document`，每次 `time.perf_counter()` 差 **< 1.0 断言**。
- test_core_isolation.py（≤50 行）：`ROOT = Path(__file__).resolve().parents[1]`；child code 字符串=断言 mycad.core 后无 build123d/OCP + import mycad.geom 后有；`subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True)`；断言 returncode==0，失败消息附 stderr。

## 5. 任务清单（预咀嚼，从 D0 顺序机械执行）
- D0：cat §2 全部参考文件+sed 两段规格。DONE D0。
- D1：edit exceptions.py（ArchiveVersionError 追加 found/supported 两默认值字段+docstring）→ `uv run pytest tests/test_exceptions.py -q` 绿 + `uv run basedpyright src/mycad/core/exceptions.py` 0 errors。DONE D1。
- D2：cat > migrations/__init__.py（≤60 行）。DONE D2。
- D3：cat > schema_v1.py 块一（常量+validate_archive 顶层/命令/metadata/组结构，≤110 行）。DONE D3。
- D4：cat >> schema_v1.py 块二（null 扫描+selector_from_json，≤90 行）→ basedpyright schema_v1.py 0 errors。DONE D4。
- D5：cat > persistence.py 块一（LoadedDocument+save_document，≤100 行）。DONE D5。
- D6：cat >> persistence.py 块二（open_document 全流水线，≤110 行）→ basedpyright persistence.py 0 errors。DONE D6。
- D7：cat > core/__init__.py（§4.1 顺序+__all__，≤60 行）→ `uv run pytest tests/test_layering.py -q` 绿 + `uv run python -c "import mycad.core"` 无错。DONE D7。
- D8：cat > tests/test_core_isolation.py → pytest 绿。DONE D8。
- D9：cat > test_persistence.py 第一批（文件头+migrations 类+恒等，≤80 行）→ 绿。DONE D9。
- D10：cat >> 第二批（异常矩阵，≤120 行）→ 红→绿（save 先行构造夹具）。DONE D10。
- D11：cat >> 第三批（往返矩阵，≤130 行）→ 绿。DONE D11。
- D12：cat > test_core_integration.py 块一（specs+装配+①②，≤110 行）→ 绿。DONE D12。
- D13：前置实验选定几何失败命令→cat >> 块二（③④⑤，≤150 行）→ 绿。DONE D13。
- D14（终验）：§6 全绿 → 追加 evidence §T6d（D13 实验选型+QA 输出摘录+性能实测值）→ 回合输出 DoneClaim。DONE D14。

## 6. scoped 验证命令（终验 D14 全跑）
- `uv run pytest tests/core/test_persistence.py tests/core/test_core_integration.py tests/test_core_isolation.py tests/core/test_bus.py tests/core/test_document.py tests/test_layering.py tests/test_exceptions.py -q` 全绿
- `uv run basedpyright src/mycad/core/__init__.py src/mycad/core/persistence.py src/mycad/core/schema_v1.py src/mycad/core/migrations/__init__.py src/mycad/core/exceptions.py tests/core/test_persistence.py tests/core/test_core_integration.py tests/test_core_isolation.py` → 0 errors, 0 warnings
- `uv run ruff check` + `uv run ruff format --check`（同上文件清单）

## 7. DoneClaim（会话尾输出，JSON 单行）
`{"task":"T6d","status":"done","deliverables":[<白名单文件>],"tests":"<终验命令输出尾行>","notes":"<偏离记录/无>"}`
