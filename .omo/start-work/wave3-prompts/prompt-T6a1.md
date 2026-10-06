# T6a1 — MyCAD core 契约层之协议片（T6 拆分 1/2：kernel_protocol + handlers + ports）

你是本仓库的实现代理。工作目录 /media/sima/Data/projects/MyCAD。本提示词与计划规格是唯一权威，逐字机械执行，零发明权。

## 反停摆硬纪律（历史上 8 个代理死于长单回合生成，违反即死）
1. 开工第一动作：直接执行下方『任务清单』的步骤 0。清单已预咀嚼完毕——**禁止先写任何清单/计划/总结文件**；每完成一步，回合文字里输出 `DONE <n>` 即可。
2. 单次文件写入硬上限 ~100 行。新文件首块 `cat > file` ≤100 行，续写一律 `cat >> file` 追加。禁止一次写整个大文件。
3. 每回合恰一个小动作：写一个文件块 / 跑一条 scoped 验证 / 读一个参考文件。三选一。
4. 禁止长篇设计推理——设计已在规格中写死，你只做机械转写。回合内文字输出保持极短。
5. 遇范围外阻塞立即输出 `BLOCKED: <原因>` 结束，勿空转。

## 通用规则
- 每个新源文件带 SPDX 两行头（参照 src/mycad/core/exceptions.py 现有头格式）。
- basedpyright strict 零逃逸：禁 type: ignore / pyright: ignore 于产品码与常规测试。**唯一例外**：tests/typing/expect_errors.py 中规格明确写死的那一行 `# pyright: ignore[reportArgumentType]`（静态锁机制的组成部分，属规格要求非逃逸）。
- TDD 垂直切片：每个模块 = 先追加 2-4 个测试（红）→ 追加实现块（≤100 行）→ scoped 验证（绿）→ 下一模块。
- 验证一律路径级 scoped 命令，禁全量套件。
- 禁止 git add/commit/stash 任何操作。
- 参考实现（只读，禁改）：src/mycad/core/exceptions.py（15 类异常：InvalidHistoryError/InvalidPlanTransition/ValidationError/UnknownCommandError/ArchiveVersionError/GeometryBuildError/TopologyReferenceError/ReplayDuringRollbackError/BatchRollbackError 等——规格引用的异常全部已存在，禁新增异常类）、src/mycad/core/selectors.py（FaceSelector/EdgeSelector 描述子）、src/mycad/core/geometry_types.py（MassProperties/BoundingBox/Tessellation）、src/mycad/commands/（registry.py 的 CommandRegistry 与 schema_defs；spec/validation 的 validate_params/normalize_params——具体位置自行 grep）、src/mycad/geom/kernel.py（BuildKernel 公开面）。

## 本片范围（白名单，越界即违规）
新建：
- src/mycad/core/kernel_protocol.py（Kernel Protocol）
- src/mycad/core/handlers.py（CommandHandler Protocol + HandlerContext + BuiltinModelingHandler）
- src/mycad/core/ports.py（ExportableKernel/FormatPort/FormatResolver 三 Protocol）
- tests/core/test_kernel_protocol.py（**已存在**——前任代理步骤 0 交付，先 cat 检查，合格直接复用进入步骤 1，不合格最小修正）
- tests/core/test_handlers.py
- tests/core/test_ports.py
禁触：src/mycad/geom/、src/mycad/commands/、tests/geom/、tests/commands/；src/mycad/core/ 下其他一切新文件（groups/signals/document/plan/bus/persistence 归并行兄弟与后续片——**不要创建**）；.omo/evidence/（由兄弟片统一写）；既有 tests/core/test_selectors.py 只读保持绿。

## 规格原文（计划 .omo/plans/phase0-mvp.md 306-349 行逐字节选，唯一权威）
（注意：本片为 T6 拆分之一。规格全文还包含 groups/signals/document/plan（兄弟片 T6a2 并行）与 bus.py/persistence.py/Document 类/集成测试大段（T6b/T6c）——均不在本片范围，不要创建相关文件。）

  What to do / Must NOT do:
  - `src/mycad/core/kernel_protocol.py`：`@runtime_checkable Kernel(Protocol)`——`reset()`、`apply(command_id: str, params: Mapping[str, object]) -> None`；**core 依赖倒置：只持有 Protocol，不 import geom**（接线在顶层 composition，T7/T10）。
  - **`src/mycad/core/handlers.py`（命令处理器契约，#7 缺失符号补齐；分派机制写死，禁止执行者另立）**：`@runtime_checkable CommandHandler(Protocol)`：`command_id: str`（**实例属性，非类属性**）+ `handle(params: Mapping[str, object], ctx: HandlerContext) -> object | None`；`HandlerContext` 为 frozen dataclass，**恰好两字段 `kernel: Kernel`（只读引用）与 `command_id: str`（当前正在执行的命令 id，由 Bus 逐调用注入）**；**返回值约定：建模处理器返回 `None`（经 kernel.apply 产生副作用），非几何命令（如插件 demo.ping）可返回任意可 JSON 序列化值**。
    - **分派唯一机制（写死）**：`BuiltinModelingHandler(command_id: str)` 构造时绑定单条命令 id（`self.command_id`），`handle` 内调 `ctx.kernel.apply(self.command_id, params)`、恒返回 None；T7 装配时为 8 条内置命令各构造一个绑定实例：`{cid: BuiltinModelingHandler(cid) for cid in BUILTIN_COMMAND_IDS}`。**禁止**让一个共享无状态实例"内部按 command_id 猜命令"（handle 不接收 id 时无法知道当前命令）；ctx.command_id 作为第二保险（Bus 必须传入与映射键一致的 id，断言二者相等）。插件工厂 `handler_factory()` 零参返回已绑定自身 command_id 的 handler 实例（demo 的 `DemoPingHandler()` 内 command_id="demo.ping"）。
    - Bus 执行时以 `handlers[id].handle(params, HandlerContext(kernel=kernel, command_id=id))` 的返回值作为 `execute()` 返回值（内置路径恒 None）；不引入全局 Result 包装类型。
  - **`src/mycad/core/ports.py`（第二倒置，为 T8 先于 T7 解环）**：定义三个 `@runtime_checkable` Protocol（core 只定义、不实现、不 import geom/formats）：
    - `ExportableKernel(Protocol)`：`reset() -> None`、`apply(command_id: str, params: Mapping[str, object]) -> None`、`mass_properties() -> MassProperties`、`export_step(path: Path) -> None`、`export_stl(path: Path) -> None`（方法名与 T2 BuildKernel 公开面逐字一致；**MassProperties/BoundingBox/Tessellation 三个中立 frozen DTO 已由 T1 在 `src/mycad/core/geometry_types.py` 唯一定义**（字段见 T1），ports.py 从同模块 import 类型；T6 只保留字段一致性消费，不新建、不重复定义，core 绝不 import geom）；
    - `FormatPort(Protocol)`：`name: str`、`vendor: str`、`priority: int`、`extensions: tuple[str, ...]`、`can_write: bool`，方法 `write(geometry: ExportableKernel, path: Path) -> None`（geometry 参数必须是 ExportableKernel，不得只写 Kernel——后者缺 mass_properties/export_* 方法，strict 下必报错）；
    - `FormatResolver(Protocol)`：`resolve(path: Path) -> FormatPort`。

  - Must NOT do：不 import geom/formats（双依赖倒置，只持 Protocol）；不做 inverse 命令；不做 BREP 内嵌/快照缓存（ADR-002 演进口）；不做 Redo 以外的多分支历史；不引第三方事件库；不做并发写锁（单线程文档模型，文档注明）；**execute_batch 不允许"返回错误对象/部分成功"语义**；ExecutedCommand/PlannedCommand/AFFECTED_OBJECTS 不在 core 外重复定义。

## 本片任务清单（已预咀嚼，从步骤 0 直接顺序机械执行；每步内部"先测试（红）→后实现→scoped 验证（绿）"；禁止先写任何清单文件，每完成一步回合文字输出 DONE <n>）
- 步骤 0：cat tests/core/test_kernel_protocol.py 检查前任交付（脚本化 FakeKernel 实现 reset/apply + isinstance(fake, Kernel) 断言）。合格 → 跑 pytest 确认当前红（模块未实现）；不合格 → 最小修正。回合结束。
- 步骤 1：写 src/mycad/core/kernel_protocol.py（SPDX 头 + @runtime_checkable Kernel(Protocol) 两方法，≤40 行）→ pytest tests/core/test_kernel_protocol.py -q 绿。DONE 1。
- 步骤 2：写 tests/core/test_handlers.py（FakeKernel 记录 (command_id, params) 调用；BuiltinModelingHandler(command_id) handle 返回 None 且调 kernel.apply；手工构造 ctx 传错 id → ValueError；command_id 为实例属性断言）。
- 步骤 3：写 src/mycad/core/handlers.py（≤100 行）→ 步骤 2 测试绿。DONE 3。
- 步骤 4：写 src/mycad/core/ports.py（三 Protocol ≤80 行；ExportableKernel 五方法与 BuildKernel 公开面逐字一致）→ ruff check 该文件。
- 步骤 5：写 tests/core/test_ports.py（import mycad.geom 的 BuildKernel——加载 build123d 慢属正常；assert isinstance(BuildKernel(), ExportableKernel)；赋值 kernel: ExportableKernel = BuildKernel()）→ 绿。DONE 5。
- 步骤 6（终验）：四门全跑（见下）→ 回合输出 DoneClaim JSON 结束。

## 本片 scoped 验证命令（终验步骤全跑）
- uv run pytest tests/core/test_kernel_protocol.py tests/core/test_handlers.py tests/core/test_ports.py tests/core/test_selectors.py -q 全绿
- uv run basedpyright src/mycad/core/kernel_protocol.py src/mycad/core/handlers.py src/mycad/core/ports.py tests/core → 0 errors, 0 warnings
- uv run ruff check src/mycad/core/kernel_protocol.py src/mycad/core/handlers.py src/mycad/core/ports.py tests/core
- uv run ruff format --check src/mycad/core/kernel_protocol.py src/mycad/core/handlers.py src/mycad/core/ports.py tests/core

## DoneClaim（结尾必须输出）
{"task":"<片名>","changed_files":[...],"tests":[命令+尾部结果],"risks":[...]}
