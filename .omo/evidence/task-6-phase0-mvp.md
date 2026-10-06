# Phase 0 / T6 evidence — core: DTO layer, signals, plan state machine (Wave 3)

**Task**: T6（拆分执行）§T6a 并行双子片：T6a1（kernel_protocol / handlers /
ports，兄弟片）+ T6a2（signals.SignalBus / document DTO / plan 状态机，本片）。
T6b/T6c（Document 聚合、bus、persistence、集成测试）不在 §T6a 范围。
**Plan**: `.omo/plans/phase0-mvp.md` T6 段（306-349 行）+ 附录 B.2 固定映射。
本文件由 T6a2 resume 第三实例落盘。
**UTC timestamp**: 2026-10-05T09:22:26Z。
**Environment**: Linux x86_64, Python 3.12.3, uv, basedpyright 1.40.1, ruff 0.6+, pytest 9。

## §T6a

### T6a1（兄弟片 — 存在性记录，验证由编排方复跑）

- 交付物（本片全程未触碰）：`src/mycad/core/kernel_protocol.py`、
  `src/mycad/core/handlers.py`、`src/mycad/core/ports.py`；
  `tests/core/test_kernel_protocol.py`、`tests/core/test_handlers.py`、
  `tests/core/test_ports.py`。
- 编排方 ledger 记录：T6a1 首例静默死亡但交付物全落盘，编排方 scoped 验收
  （pytest 8 passed + basedpyright 0）。本片 R6 门禁按提示词要求仅点名本片
  文件；T6a1 文件的最终验证以编排方复跑为准，不在此处门禁内。

### T6a2（本片）交付清单

| 文件 | 内容 |
|---|---|
| `src/mycad/core/signals.py` | 追加 SignalBus 类：subscribe 弱持有（经 _make_ref）+ TypeError 强持有回退；emit 缺省 payload 投 `{}`；按名隔离；监听器异常→RuntimeWarning 隔离；死引用投递时静默丢弃 |
| `src/mycad/core/document.py` | DTO 唯一定义点：CommandAmendment(at/actor/from_params/reason)；ExecutedCommand 六审计字段 + amendments 默认 ()；AffectedObject 八值 Literal；AFFECTED_OBJECTS（B.2 映射，`Mapping[str, str]`）；PlannedCommand（运行时 id 查表门→UnknownCommandError(identifier)）；尾部 `# T6b: Document 类在此追加` 占位 |
| `src/mycad/core/plan.py` | Plan/PlanStatus 六态状态机；`_LEGAL` 六边唯一权威表；confirm 空 actor ValueError（先校验后转移，原子）；mark_executing/mark_done/mark_failed/cancel；plan_id 缺省 uuid4().hex 32 位小写只读（__setattr__ 守卫） |
| `tests/core/test_document_dtos.py` | 10 例：get_args 八元组与 set(AFFECTED_OBJECTS.values()) 同源；B.2 全表锁定；表外 id→UnknownCommandError；frozen×2；amendments 默认空/携带；六审计必填字段名序锁 |
| `tests/core/test_plan_state_machine.py` | 34 例：6 合法边逐边；confirm("") 原子拒绝；3 终态×5 动作参数化拒绝；9 非法非终态对参数化拒绝；字段序 steps 在前+默认值；Plan(steps) 构造合法；plan_id 32 位小写 hex；plan_id 只读 |
| `tests/typing/expect_errors.py` | 正向：八字面量赋值无 ignore；负向：单行 bogus + `# pyright: ignore[reportArgumentType]`（规格写死的唯一 ignore 例外） |

### 验证输出尾部（R6 四门，2026-10-05 本机复跑，文件按提示词逐一点名）

```
$ uv run pytest tests/core/test_groups.py tests/core/test_signals.py \
    tests/core/test_document_dtos.py tests/core/test_plan_state_machine.py \
    tests/core/test_selectors.py -q
64 passed in 0.26s

$ uv run basedpyright src/mycad/core/groups.py src/mycad/core/signals.py \
    src/mycad/core/document.py src/mycad/core/plan.py tests/core/test_groups.py \
    tests/core/test_signals.py tests/core/test_document_dtos.py \
    tests/core/test_plan_state_machine.py tests/core/test_selectors.py tests/typing
0 errors, 0 warnings, 0 notes

$ uv run ruff check <同上文件清单>
All checks passed!

$ uv run ruff format --check <同上文件清单>
10 files already formatted
```

篡改探针（静态锁红→绿闭环）：去除 expect_errors.py 的
`# pyright: ignore[reportArgumentType]` → basedpyright 报
`1 error ... (reportArgumentType)`；还原 → 0 errors。静态锁有效力。

### 偏离记录（前任遗留缺陷修复 ×5 + 规格歧义裁决 ×5）

前任"已验证完整"的遗留文件实际只过 pytest 门、未过 basedpyright/ruff 门
（R0/R6 门禁复现）；以下修复均为 R6 门禁所强制，逐条记录：

- **D1 signals.py 头部 import 块未排序（ruff I001）**：`import weakref`
  机械移入排序位，行为零变化。
- **D2 signals.py 头部 `_BoundBuiltinRef` 对不可弱引用属主抛 TypeError**：
  普通属主（如 `list`）不可 weakref，`weakref.ref(meth.__self__)` 直接抛错
  （R0 时 pytest 5 failed 复现）。修复收在本片允许追加的 SignalBus 类本体内
  ——subscribe 捕获 TypeError 回退为强持有（闭包）；前 65 行其余字节零改动；
  可弱引用回调的弱持有语义不变。
- **D3 groups.py reportUnnecessaryIsInstance ×2**：`__post_init__` 改为无条件
  `tuple()` 规范化——精确 tuple 输入时 `tuple(t) is t`，行为等价；tuple 子类
  输入被规范化为精确 tuple，语义更严。
- **D4 test_groups.py reportUnusedImport**：函数内副作用导入改为
  `importlib.import_module("mycad.core.groups")`，语义等价。
- **D5 test_signals.py ruff format 偏差**：末行 assert 按格式器输出折叠为
  单行（98 字符）。
- **D6 规格张力**：R1 清单字面 `len(fields(ExecutedCommand))==6` vs 规格
  "六审计字段 + 外加 amendments 字段（不计入六字段计数，存档空时不出现
  键）"。以规格为唯一权威：7 字段 = 6 必填审计 + amendments（默认 ()）；
  测试锁定 6 个必填审计字段名序 + amendments 为唯一附加可选字段。
- **D7 PlannedCommand 运行时门仅按 id**：规格 B.2 节"构造时查表，查不到
  id→UnknownCommandError"；affected_object 值由 Literal 静态门 + T10 B.1
  加载器级校验（值≠B.2[id]→ValidationError）覆盖，DTO 层不发明值检查。
- **D8 plan_id 只读实现**：规格"构造后 plan_id 只读"未给实现细则；取
  `__setattr__` 守卫抛 AttributeError（与 frozen dataclass 行为族一致）。
- **D9 规格算术歧义**："3 终态×6 请求动作"（实存转移方法仅 5 个）与"共 8
  个跨态跳跃"（明列仅 7 个）。以六边表为唯一权威做全穷举：3 终态×5 动作
  =15 拒绝 + 全部 9 个非法非终态对（15 非终态对−6 合法边），为两种读法的
  超集。
- **D10 T6b 占位注释位置**：R2 文字"第一半含占位"与范围节"文件尾留占位"
  矛盾，以范围节为准置于文件尾。
- **D11（编排方验收修复）test_groups.py CAD 泄漏断言改子进程模式**：
  a1 test_ports.py 顶层 `from mycad.geom.kernel import BuildKernel`（真核
  协议兼容测试，合法需求）在共享 pytest 会话把 build123d 带入
  sys.modules，本片进程内断言在全目录运行时必败（隔离运行绿，掩盖问题）。
  修复对齐 test_selectors.py / test_signals.py 既有子进程模式，语义不变
  （模块净化本质是新解释器属性）。修复后 tests/core/ + test_exceptions
  = 86 passed 全绿。

### 风险与移交 T6b/T6c 备注

- D2 强持有回退仅影响"不可弱引用属主的内建绑定方法"（如 `list.append`）：
  此类回调本就无法弱持有，总线改持其闭包强引用直至总线自身被弃。
- InvalidPlanTransition 以规格字面两参 `InvalidPlanTransition(from_status,
  requested)` 抛出（dataclass 字段映射 message=from_status、
  command_id=requested）。
- expect_errors.py 依赖文件名不匹配 `test_*.py` 而不入 pytest 收集；
  basedpyright 扫描该目录（R3/R6 已覆盖）。
- Plan 非冻结（转移方法就地改 status/confirmed_by）；"纯函数转移"按
  "无 LLM/网络/IO 副作用、仅状态推进"语义实现。

## §T6b（Document 聚合类 — 编排方验收采信）

### 采信依据

T6b 实例（ses_ef490dbfaffeeoTTk41j6BGhGT）于 2026-10-05 17:52:38 被
5 小时配额墙击杀（与主编排会话同一中断事件）：尾消息为 step-start 空
部件，倒数第二条为四门自报（pytest 45 已通过 / basedpyright 0/0 /
ruff check 通过 / format 2 已格式化）+ 占位完整性自查 bash 调用——
死因是配额墙而非推理停摆（有持续输出直至击杀瞬间）。DoneClaim 与本
节 evidence 因击杀缺失；交付物完整落盘，编排方按 a1 先例复跑 scoped
四门采信，规格符合性由编排方逐行审阅确认。

### 交付清单

| 文件 | 内容 |
|---|---|
| `src/mycad/core/document.py`（91→277 行） | Document 聚合类追加于占位处；DTO 半区（1-91 行）字节未动（占位注释仍第 91 行，test_document_dtos 10 例全绿锁定 DTO 行为） |
| `tests/core/test_document.py`（180 行，17 例） | 构造/metadata/组 API/replace_command_params/内部 API 全覆盖 |

### 验证输出尾部（编排方复跑，2026-10-05，scoped 点名）

```
$ .venv/bin/python -m pytest tests/core/test_document.py tests/core/test_document_dtos.py tests/core/test_groups.py tests/core/test_signals.py -q
45 passed in 1.21s
$ .venv/bin/basedpyright src/mycad/core/document.py tests/core/test_document.py
0 errors, 0 warnings, 0 notes
$ .venv/bin/ruff check <同两文件> && .venv/bin/ruff format --check <同两文件>
All checks passed! / 2 files already formatted
```

### 偏离记录（D12-D16）

- **D12 UTC 别名**：`datetime.now(UTC)`（`datetime.UTC`，UP017 现代写法）
  替代提示词钉死的 `datetime.now(timezone.utc)`，语义等价。
- **D13 set_metadata 运行时值检查**：规格只钉 key 白名单；实现追加
  `isinstance(value, str)` 防御（否则 ValidationError），并以
  `cast("object", value)` 保持 pyright 非冗余。
- **D14 置脏策略**：`_restore_metadata`/`_restore_commands`/
  `_pop_commands` 均置脏。规格未明说；批回滚/编辑回滚语义=文档相对
  上次保存已变更（历史或元数据被改写），置脏正确。`metadata`/
  `named_groups` property 返回浅拷贝 dict（组值 NamedGroup 不可变，
  浅拷贝足够）。
- **D15 占位注释保留**：`# T6b: Document 类在此追加` 保留于第 91 行
  （DTO 半区字节同一性证据），第 93 行顶层 import 后置以 `noqa: E402`
  标注并说明原因。
- **D16 import 最小化超出钉死**：提示词仅钉死 validate_params 局部
  import；实现将 exceptions/signals/validation 及 dataclasses 工具
  全部下沉到函数体（模块级运行时 import 仅 typing + DTO 半区原有）。
  更保守，为 T6d `core/__init__.py` 聚合导入消除一切环风险。

### 规格符合性（编排方逐项审阅确认）

构造签名 `Document(registry, *, metadata, commands, named_groups)` ✓；
METADATA_KEYS 六元组含 part_name/notes、DEFAULT_METADATA 恰四键 ✓；
events=SignalBus()、is_dirty 初 False、mark_clean() ✓；commands
property→tuple ✓；Bus 内部 API `_append_command/_pop_commands(n)/
_restore_commands(snapshot)` ✓；metadata_snapshot/_restore_metadata ✓；
set_metadata 信号 payload={"key","value"} ✓；组 API name 非空 str +
重名 ValidationError + remove 缺失 KeyError + 信号 payload={"name"} ✓；
replace_command_params：ordinal 越界→InvalidHistoryError、validate 先
于一切变更（deepcopy 快照在其后）、不做 normalize（Bus 唯一规范化点）、
dataclasses.replace 保留 ordinal/timestamp_utc/confirmed_by、
CommandAmendment(at=utc isoformat, from_params=dict(旧))、信号 payload=
{"ordinal","command_id"} ✓；类 docstring 注明单线程模型 ✓。

## §T6c（CommandBus — 编排方验收采信）

### 采信依据

T6c 实例（ses_ef3b771c3ffeIMWAXz7wsxsZ20）2026-10-05 22:00:18 尾消息
完整 DoneClaim JSON；自报四门绿。编排方复跑：pytest 5 文件 61 passed /
basedpyright bus.py+exceptions.py+test_bus.py 0 errors / ruff check+format
clean。bus.py 235 行逐行对照钉死规格全部符合（构造不校验覆盖、
_execute_one 唯一流水线 handler 检查先于 validate、pre/post 信号仅
record=True、undo/redo 长度先验原子性+单次 _rebuild、redo 追加原实例
保留审计字段、_rebuild ordinal 缺失包装+尾部 geometry_rebuilt、
edit_and_replay 双快照回滚+单失败带 ordinal 重抛+二败
ReplayDuringRollbackError、execute_batch mark_executing 前置+失败恢复
快照+mark_failed 先于抛错+BatchRollbackError 四字段+二败包装）。
**篡改探针红绿闭环**：sed 注释掉 execute_batch 两处快照恢复调用 →
test_bus 3 failed（批回滚测试有牙齿）→ 还原 → 27 passed。

### 交付清单

| 文件 | 内容 |
|---|---|
| `src/mycad/core/bus.py`（新建 235 行） | CommandBus 四块：构造（redo 栈+Document 内部 API cast 绑定）/execute+_execute_one/_validate_n+undo+redo+_rebuild/edit_and_replay+execute_batch |
| `tests/core/test_bus.py`（新建 456 行，27 例） | FakeKernel/FakeHandler/EchoHandler/装配夹具、分派+ctx 锁定、confirmed_by 三语义、undo/redo 参数化+原子性、edit_and_replay 四场景、execute_batch 五场景、normalize 删键+旁路闭集 |
| `src/mycad/core/exceptions.py`（修改） | BatchRollbackError += failed_ordinal/failed_command_id/reason/executed_ids 默认值；ReplayDuringRollbackError += original/replay_reason；15 类顺序未动 |

### 偏离记录（D17-D23，源自 DoneClaim risks 编排方复核采信）

- **D17 cast(getattr) 构造期绑定**：pyright reportPrivateUsage 禁止
  bus.py 直书 document._append_command 等 Bus 面内部 API；构造期
  `cast(getattr(document, "_append_command"))` 绑定一次（运行时同一
  bound method，行为等价），4 处 `noqa: B009`（ruff B009 与 pyright
  结构性冲突，repo 已有 noqa 先例）。
- **D18 UP017**：`datetime.UTC` 替代 `timezone.utc`（py312 target 下
  ruff 强制），与 D12 同族。
- **D19 C8 场景②任务书正文与断言矛盾**：以断言为准（步骤
  [demo.a, feature.cylinder 非法]，failed_ordinal==1、
  executed_ids==("demo.a",)）。
- **D20 AFFECTED_OBJECTS 测试扩表**：PlannedCommand __post_init__ 锁
  八 builtin 键而任务书夹具要求 demo.a/demo.b 入 plan；测试内
  monkeypatch.setitem 临时扩表（逐测试还原，src 不动）。
- **D21 normalize 旁路断言改 import/调用点闭集**：grammar.py/
  __init__.py docstring 文本提及 normalize_params，纯文本包含断言恒
  红；改按 import/调用点闭集断言（geom 目录文本级断言原样保留）。
- **D22 SignalBus 弱持有与 lambda**：subscribe(lambda) 被立即回收致
  计数 0（弱引用语义正确工作）；测试改持活列表 bound method。
- **D23 行数预算**：批次 ≤85/90 行预算在完整夹具+全钉死断言下不可
  达；按反停摆纪律拆多个 ≤100 行块执行，test_bus.py 总量 456 行
  （超 ≤380 指导值，批次预算精神保持）。

### 语义注记

- redo 重放追加**原实例**（ordinal/timestamp_utc/confirmed_by/
  amendments 保留为首次执行的审计值，按钉死规格）；后续 execute 的
  ordinal=len(commands) 0-based 自增。
- edit_and_replay 成功后 redo 清空、脏标记保持置位（规格歧义按
  "edit=未保存变更"语义，docstring 记录裁决）。

## §T6d（persistence + schema_v1 + migrations + core/__init__ + 测试 — 续作实例）

### 采信依据

T6d 续作实例（resume R1-R7，2026-10-06）完成 D9-D14。D0-D8 交付
（exceptions 扩展/migrations/schema_v1/persistence/core/__init__/
隔离测试）由编排方 2026-10-06 17:40 验收采信，本实例未改动。
终验 §6 三门复跑全绿：pytest 七文件 86 passed；编排方口径加跑
tests/core 全目录+三根测试 166 passed（139 旧+27 新，零回归）；
basedpyright 八文件 0 errors/0 warnings；ruff check+format --check
八文件 clean。test_persistence.py 366 行 21 例，test_core_integration.py
268 行 6 例。

### D13 失败命令实验选型（前置实验，python -c 实证）

首选方案一次命中，未启用备选：
`modify.fillet` radius=999.0 on 10mm box（edges=[{parent_faces:
[{surface:"plane",axis:"+Z"}]}]）→ `GeometryBuildError("modify.fillet:
build123d fillet failed (radius=999.0): Failed creating a fillet with
radius of 999.0, try a smaller value or use max_fillet() ...")`。
与 tests/geom/test_features.py 既有 `test_fillet_radius_beyond_geometry_
raises_geometry_build_error` 结论一致；boolean_cut 空工具体备选未启用。

### QA happy path 输出摘录（③ 场景同构内联脚本）

```
combined volume : 6219.9115 (analytic 6219.9115)   # box 10x20x30 + π·2²·4 + π·3²·6（disjoint add）
after undo(2)   : 6000.0000 (box analytic 6000.0)
after open      : 6219.9115                          # 新装配 open_document 一次 _rebuild
  ordinal=0 id=feature.box v=1 confirmed_by='cli-local' ts=2026-10-06T09:59:49.592432+00:00 params=[center,mode,size_x,size_y,size_z]
  ordinal=1 id=feature.cylinder v=1 confirmed_by='cli-local' ts=2026-10-06T09:59:49.599024+00:00 params=[center,height,mode,radius]
  ordinal=2 id=feature.cylinder v=1 confirmed_by='cli-local' ts=2026-10-06T09:59:49.604376+00:00 params=[center,height,mode,radius]
six audit fields complete on all 3 commands: True
```

### 性能门实测（NF-05/NF-04：10 命令 box/cylinder 存档 × 10 次 open_document）

```
replay wall-clock ms: [89.0, 74.9, 54.9, 55.3, 58.8, 55.9, 61.1, 57.9, 63.2, 78.3]
```

最慢 89.0ms，门限 1000ms（断言 worst < 1.0s，超时即失败）。为
ADR-002 brep 缓存演进留基线。

### 偏离记录

- **批次划分**：任务书 §4.5 原文要求 test_persistence.py "≥4 批 cat"；
  resume 提示词 R2-R4 收敛为 3 批。实际按 ≥4 执行：76/126/56/108 行
  四批（每批后 scoped pytest），总量 366 ≤ 380；126 行批超 resume 子
  预算 120、低于反停摆硬顶 150（完整夹具+装配函数所占，D23 同族）。
- **异常矩阵拆两批**：夹具（FakeKernel/EchoHandler/demo.sel 装配+
  seed_archive/tamper）占 ~58 行，异常 11 例无法压进单批 120 行，
  拆"结构/预检/几何失败"+"版本/格式/显式 null"两批达成。
- **FakeHandler 未复刻**：persistence 测试无 demo.ping 场景，仅自造
  FakeKernel/EchoHandler（同 test_bus.py 形态）。
- **集成测试自建 defs 简化**：FaceSelector 仅 plane 分支（fillet 用例
  仅用 plane +Z 谓词）；cylinder 分支与正式 COMMAND_SCHEMA_DEFS 是
  T7 职责。specs 以 $ref 引用单一 _DEFS 表，无第二处正式表。
- **amendment from_params 断言**：normalize 填默认后 from_params 为
  完整参数（含 center/mode），首跑红；改锁定 from_params["radius"]/
  actor/reason + 与源文档 amendments 元组整体相等（绿）。
- **①/QA 场景命令数**：任务书"box+cylinder(add) 三命令"，实现为
  box(new)+2×cylinder(add) disjoint——undo(2) 后恰剩 box（体积==box
  解析值）与断言语义一致。
- **④ step 编号**：validate 失败 failed_ordinal==1、几何失败
  failed_ordinal==2（0-based，与 test_bus.py 既有约定一致）。
- **ruff format 机械重排**：两个新测试文件各跑一次 `ruff format`
  （仅 join/split 行与尾逗号归一，无语义变化；format --check 终验绿）。
- **B905/未用变量**：zip 补 strict=True；未用解包变量改 `_` 前缀
  （basedpyright strict 报告驱动，语义不变）。

### 交付清单

| 文件 | 内容 |
|---|---|
| `tests/core/test_persistence.py`（新建 366 行，21 例） | migrations 链 4 例（恒等/注册 hop/未知版本文案含"3"与计数/出厂空表）；open 异常矩阵 11 例（malformed/未知 metadata 键无部分构造/未知顶层键/缺 handler 含 ordinal+id/未注册 id/第 2 条几何失败 ordinal==1/version=99 字段对/format 篡改+缺失字段对/axis·rank 显式 null 篡改）；往返矩阵 6 例（六字段+amendments+timestamp 相等+空键不现/两组混合 selector 逐字段+空列表显式 []+EdgeSelector 无 curve/remove 后键消失/cylinder 无 axis wire 省略+open 恢复/saving·saved 各一次含 path/父目录 OSError+无 .tmp 残留） |
| `tests/core/test_core_integration.py`（新建 268 行，6 例） | 自建 box/cylinder/fillet specs（$defs 单表）+BuiltinModelingHandler+真 BuildKernel；①execute/undo(2)/redo(2) 体积解析值；②edit_and_replay πr²h；③QA happy path 三命令往返六字段；④真核批回滚两场景（validate 失败+fillet 999 几何失败，BatchRollbackError 四字段+历史无批命令+体积回批前+plan failed）；⑤性能门 10×open 断言 <1000ms |

## §T6 终验（编排方，2026-10-06 18:20 CST）

- **全量四门一次通过**：ruff check 全过 / ruff format 81 files / basedpyright 0 errors 0 warnings 0 notes / pytest **466 passed**（T5 基线 128 → T6 净增 338 例）。
- **篡改探针红绿闭环（T6d 片，语义级）**：`open_document` 逐命令预检 `_require_command` 调用行 pass 化 → `test_open_missing_handler_names_ordinal_and_id` 精确 1 failed（20 passed）→ 还原 → 21 passed。探针证明测试锁住预检逻辑而非语法脆弱性。
- **性能门实测**：open_document 重放最慢 89.0ms（NF-04 门限 1000ms，test_core_integration.py 断言 worst < 1.0）。
- **隔离门**：tests/test_core_isolation.py 子进程断言 import mycad.core 后 build123d/OCP 不在 sys.modules（core/__init__.py 聚合导入给隔离测试装上牙齿）；tests/test_layering.py 同步绿。
- **T6 四片采信链**：T6a1（协议，静默死采信）/ T6a2（DTO+状态机+signals，三次重派后 DoneClaim 完整）/ T6b（Document，配额墙击杀交付完整采信）/ T6c（CommandBus，DoneClaim 完整）/ T6d（persistence src 侧配额墙采信 + resume 实例测试片 DoneClaim 完整）。偏离记录 D1-D32 逐段在案。
