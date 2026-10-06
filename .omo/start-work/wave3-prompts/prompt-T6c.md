# T6c — MyCAD core 之 CommandBus（T6 拆分 4：单命令/undo/redo/编辑重放/批事务）

你是本仓库的实现代理。工作目录 /media/sima/Data/projects/MyCAD。本提示词与计划规格是唯一权威，逐字机械执行，零发明权。

## 前置磁盘现状（编排方已核实，直接采信）
- `src/mycad/core/document.py` 已含完整 Document 类（DTO 半区 + T6b 追加半区）：构造 `Document(registry, *, metadata=None, commands=None, named_groups=None)`；`commands` property→tuple；`is_dirty`/`mark_clean()`；Bus 面内部 API `_append_command(command)`/`_pop_commands(n)`（弹末尾 n 条，返回 list）/`_restore_commands(snapshot)`；`metadata_snapshot()`/`_restore_metadata(snapshot)`；`replace_command_params(ordinal, params, actor, reason)`（校验失败 ValidationError、ordinal 越界 InvalidHistoryError、成功追加 CommandAmendment 并发 command_amended 信号）。→ 只读。
- `src/mycad/core/plan.py` 已交付：`Plan(steps, status="draft", plan_id=uuid4hex, confirmed_by=None)`、`confirm(actor)`（空 actor ValueError）/`mark_executing()`/`mark_done()`/`mark_failed()`/`cancel()`，非法转移抛 `InvalidPlanTransition`。→ 只读。
- `src/mycad/core/signals.py`：`SignalBus`，`subscribe(name, cb)`/`emit(name, payload=None)`（缺省投递 `{}`），经 `document.events` 发射。→ 只读。
- `src/mycad/core/handlers.py`：`CommandHandler` Protocol（实例属性 `command_id` + `handle(params, ctx)`）、`HandlerContext` frozen（恰 `kernel`/`command_id` 两字段）、`BuiltinModelingHandler(command_id)`。→ 只读。
- `src/mycad/core/kernel_protocol.py`：`Kernel` Protocol（`reset()`/`apply(command_id, params)`）。→ 只读。
- `src/mycad/core/exceptions.py`：15 类闭合。`MycadError(message, command_id=None)`；`UnknownCommandError` 另有 `identifier: str = ""`；`GeometryBuildError`/`TopologyReferenceError` 另有 `ordinal: int | None = None`；`BatchRollbackError`/`ReplayDuringRollbackError` 目前纯基类字段——**本片授权给这两类追加默认值字段（见钉死设计），其余 13 类禁触**。
- `tests/test_exceptions.py`（注意在 tests/ 根，非 tests/core/）锁：15 类名单与数量、ordinal 字段存在于两类、UnknownCommandError.identifier——追加默认字段不破坏任何断言（编排方已核实）。
- T3：`CommandRegistry(schema_defs=None)`/`.register(spec)`/`.get(id, version=None)`（未命中抛 UnknownCommandError）/`.schema_defs`；`validate_params(spec, params, defs)`→新 default-filled dict；`normalize_params(params)`→dict（删空串选择器键：`surface="cylinder"` 且 `axis:""` → 删 axis 键；`plane`+`axis:""` → 抛 ValidationError；`curve:""` → 删 curve 键；幂等）。均在 `src/mycad/commands/validation.py`。
- `src/mycad/commands/demo.py`：`demo_registry()`。`CommandSpec(id, version, summary_en, label_zh, params_schema, cli: CliSyntax, undo_compensation="history_replay")`；`CliSyntax(verb_aliases, positional=())`。

## 反停摆硬纪律（历史上 9 个代理死于长单回合生成，违反即死）
1. 开工第一动作：直接执行下方『任务清单』的步骤 C0。**禁止先写任何清单/计划/总结文件**；每完成一步，回合文字里输出 `DONE C<n>` 即可。
2. 单次文件写入硬上限 ~100 行。首块 `cat > file` ≤100 行，续写一律 `cat >> file` 追加。
3. 每回合恰一个小动作：写一个文件块 / 跑一条 scoped 验证 / 读一个参考文件。三选一。
4. 禁止长篇设计推理——设计已在规格中写死，你只做机械转写。回合内文字输出保持极短。
5. 遇范围外阻塞立即输出 `BLOCKED: <原因>` 结束，勿空转。

## 通用规则
- SPDX 两行头参照 src/mycad/core/exceptions.py。
- basedpyright strict 零逃逸：禁 type: ignore / pyright: ignore。
- TDD 垂直切片：先追加测试（红）→ 追加实现块 → scoped 验证（绿）→ 下一片。
- 验证一律路径级 scoped 命令，禁全量套件。
- 禁止 git add/commit/stash 任何操作。
- 参考实现（只读，禁改）：src/mycad/core/ 下 document.py/plan.py/signals.py/handlers.py/kernel_protocol.py/exceptions.py、src/mycad/commands/validation.py、src/mycad/commands/registry.py、src/mycad/commands/demo.py、tests/test_exceptions.py。

## 本片范围（白名单，越界即违规）
修改（仅追加字段，禁改其他 13 类与文件其余内容）：
- src/mycad/core/exceptions.py（BatchRollbackError、ReplayDuringRollbackError 两类追加默认值字段 + 各自 docstring 可修正）
新建：
- src/mycad/core/bus.py（≤240 行，分 4 块写）
- tests/core/test_bus.py（≤380 行，分 5 批写）
禁触：src/mycad/core/ 其他一切文件、src/mycad/geom/、src/mycad/commands/、tests/geom/、tests/commands/、既有全部测试文件（只读）；persistence.py/schema_v1.py/migrations/、真 BuildKernel 集成、性能门、core 隔离测试（归 T6d 片）；.omo/evidence/（归终验）。

## 规格原文（计划 .omo/plans/phase0-mvp.md T6 段逐字节选，唯一权威）
- `bus.py`：`CommandBus(document, registry, kernel, handlers: Mapping[str, CommandHandler])`——构造时 handlers 至少含全部已注册命令的处理器（T7 装配 BuiltinModelingHandler，T9 追加插件处理器；未命中处理器抛 UnknownCommandError）；单命令 `execute(command_id, params, confirmed_by=None) -> object | None`：**命令处理流水线在本方法内写死为唯一顺序 `validate_params(spec, params, defs=registry.schema_defs) → normalize_params(params) → handlers[id].handle(normalized, ctx)`（#round11-2：defs 唯一来源=构造注入的 registry.schema_defs，_execute_one/execute_batch/open_document 自动重放同走本流水线同一 defs；Bus 是规范化的唯一调用点；handler 与 geom 只接收已规范化 dict，禁止各自再规范化）**→ 发 pre_command（在 validate 通过之后、handle 之前）→ 取值 → 成功才追加历史（分配 ordinal/时间戳/confirmed_by）→ 发 post_command → 返回处理器值；**任何新命令成功执行都清空 redo 栈**（含 undo 之后再 execute）；`undo(n: int = 1)`：把末尾 n 条命令整体弹出到 redo 栈（保持原顺序）后只做一次 `_rebuild()`（reset 后顺序重放剩余历史；不逐条重放）；`redo(n: int = 1)` 对称弹回 n 条后一次重建。**n 语义写死**：缺省 n=1；n 必须为 ≥1 的整数；历史/redo 栈长度不足 n 时**在任何变更之前**抛 `InvalidHistoryError(action)`，历史与几何保持原子不变（先校验长度再弹栈）；空历史 undo、空 redo 栈 redo 同此异常。CLI 层解析（T10 事，本片不做）：`undo`/`redo` 无参数=1；非正整数或非整数→CliSyntaxError 退出码 2；栈不足→退出码 1。`undo(n)`/`redo(n)` 本身不产生历史条目；
- **`edit_and_replay(ordinal, params, actor, reason) -> None`（#10 几何侧）**：批前快照（同 execute_batch 的深拷贝纪律）→ `document.replace_command_params(...)`（校验失败直接抛出，几何未动）→ `_rebuild()`：reset 后用修订后的历史顺序重放，**任一步几何失败：恢复快照（params 与修订记录一并回滚）、再 `_rebuild()` 回到编辑前几何，仍失败则抛 `ReplayDuringRollbackError(original=<触发命令的几何异常>, replay_reason=...)`；单次重放失败（回滚成功）把触发命令的 GeometryBuildError/TopologyReferenceError 包装为带 ordinal 的同一异常类型原样抛给调用方**；成功后清空 redo 栈、脏标记、发 geometry_rebuilt。
- `execute_batch(plan: Plan)`：**前置状态契约=plan.status 必须为 `"confirmed"`**（否则 InvalidPlanTransition）；进入时调 `plan.mark_executing()`（confirmed→executing，边③）→ **批前快照**（深拷贝 commands 列表+metadata，不复制几何）→ 逐条执行，**每条 step 走与单命令相同的 `validate_params → normalize_params → handler.handle` 流水线（复用内部 `_execute_one`，禁止批路径另写一套）；step 经 normalize 后的 params 才是写入历史与 geom 的 params**；`confirmed_by` 统一取 `plan.confirmed_by` 并写入本批每条 ExecutedCommand → **全部成功：调 `plan.mark_done()`（executing→done，边⑤）后正常返回**；任一失败：恢复快照 + `_rebuild()` 回滚到批前几何状态、调 `plan.mark_failed()`（executing→failed，边⑥）、**固定且唯一地抛 `BatchRollbackError(failed_ordinal, failed_command_id, reason, executed_ids)`**（executed_ids 为本批已成功执行的命令 id 有序元组；不返回错误对象、不吞异常；失败也先完成状态转移再抛错）；回滚中的 `_rebuild()` 若二次失败，抛 `ReplayDuringRollbackError(original=BatchRollbackError, replay_reason=...)` 保留两者信息；重放途中 TopologyReferenceError 必须原样带命令 ordinal 透传（包装进 BatchRollbackError.reason 链）。
- **规范化三入口同一顺序（#round7-1，集成测试锁定）**：所有进入 geom 的路径必须经过 Bus 流水线——①交互式/脚本单行走 `execute`；②`begin-batch`/`run --json` 经 `execute_batch` 的 `_execute_one`；③`open_document` 自动重放走 Bus 内部同一 `_execute_one`（存档中的 params 是已规范化形态，仍过 validate_params 做结构校验，normalize 对其幂等）。**禁止 open 重放路径绕过流水线直接调 kernel.apply**。集成测试：一条 `feature.cylinder`（schema 合法形态含 `axis:""` 的谓词位置）经 Bus 执行成功且到达 geom 的 params 中对应值为 None（FakeKernel 记录收到的 dict 断言）；直接把未规范化 dict 喂给 BuildKernel 的旁路测试必须失败/不被产品代码允许（geom 层对 plane 空串有防御性报错即可）。
- **confirmed_by 权威规则（#round7-6）**：①交互式 REPL 与脚本普通建模行——`confirmed_by="cli-local"`；②③批路径——批内每条 ExecutedCommand.confirmed_by 必须等于 plan.confirmed_by；④Python API 直接调 `bus.execute(cid, params)` 省略 confirmed_by 时才为 null。
- 测试段（本片相关）：处理器契约单测（FakeHandler command_id="demo.ping" 返回 "pong" 经 bus.execute 原样透传且历史照记一条；注册缺失处理器的 id 执行抛 UnknownCommandError）；分派锁定测试（同一 handler 类 `EchoHandler(command_id)` 分别以 "demo.a"/"demo.b" 构造两个绑定实例，handle 断言 ctx.command_id == self.command_id 并返回该 id；ctx.command_id 与映射键不一致的注入必须触发断言）；redo 栈在新命令后被清空、空历史 undo/redo 报 InvalidHistoryError；undo/redo 的 n 参数语义参数化（undo(3) 一次弹 3 条且只触发一次 _rebuild，FakeKernel 计数 reset/apply 次数断言；redo(2) 对称恢复；历史长度不足时 InvalidHistoryError 且变更前历史/几何不变——先执行合法 undo 制造 redo 栈，再 redo(99) 断言栈与几何都未动）；edit_and_replay 四场景（①改 cylinder radius 后几何重放为新解析结果、同一 ordinal、timestamp_utc 前后字符串相等、amendments 追加 1 条含 from_params ②radius=-1 ValidationError 且几何/历史/amendments 均不变 ③重放几何失败（FakeKernel 注入第 2 条失败）时 params 与 amendments 回滚、几何回到编辑前、抛出的异常带 ordinal ④FakeKernel 注入"回滚 _rebuild 也失败"→ ReplayDuringRollbackError(original, replay_reason)）；execute_batch 状态机与回滚（①成功批 plan.status 走完 confirmed→executing→done ②两失败场景（第 2 条 validate 失败、第 3 条几何失败）均断言抛 BatchRollbackError 且 failed_ordinal/failed_command_id/reason/executed_ids 四字段值正确、几何与历史整体回到批前（失败批任何命令都不在历史里）、plan.status="failed" ③对 status="draft"/"done" 的 plan 调 execute_batch → InvalidPlanTransition；ReplayDuringRollbackError 批路径用 FakeKernel 注入"回滚重放也失败"单测）；信号订阅/异常隔离（含 command_amended 触发一次）；confirmed_by 语义（bus.execute(...,confirmed_by="cli-local") 后 history 该命令 confirmed_by=="cli-local"；execute_batch 后批内每条 confirmed_by 等于 plan.confirmed_by，参数化 plan actor="cli-local"/"acceptance-test" 两例；Python API 省略时为 None）。

## 编排方钉死的设计（唯一自由度已收敛，逐条照抄）
### 构造与状态
- `def __init__(self, document: Document, registry: CommandRegistry, kernel: Kernel, handlers: Mapping[str, CommandHandler]) -> None`：存 `self._document`/`self._registry`/`self._kernel`/`self._handlers`（内部持 `dict(handlers)` 拷贝）；`self._redo_stack: list[ExecutedCommand] = []`。**不做构造期 handlers 覆盖校验**（执行期未命中才抛 UnknownCommandError；open 失败测试需要"故意缺 handler 的装配"能成立）。
- 类 docstring 注明：单线程文档模型；Bus 是 validate→normalize 唯一调用点。
### _execute_one（唯一流水线，execute/execute_batch/重放共用）
- `def _execute_one(self, command_id: str, params: Mapping[str, object], confirmed_by: str | None, *, record: bool = True) -> object | None`。
- 顺序：①`spec = self._registry.get(command_id)`（未命中 UnknownCommandError 由 registry 抛出，原样传播）→ ②`handler = self._handlers.get(command_id)`，None 则 `raise UnknownCommandError(f"no handler registered for {command_id!r}", command_id=command_id, identifier=command_id)`（handler 检查先于 validate，fail-fast）→ ③`validated = validate_params(spec, dict(params), defs=self._registry.schema_defs)` → ④`normalized = normalize_params(validated)` → ⑤record=True 时 `self._document.events.emit("pre_command", {"command_id": command_id})` → ⑥`ctx = HandlerContext(kernel=self._kernel, command_id=command_id)` → ⑦`result = handler.handle(normalized, ctx)` → ⑧record=True 时 `self._document._append_command(ExecutedCommand(id=command_id, version=spec.version, params=dict(normalized), ordinal=len(self._document.commands), timestamp_utc=datetime.now(timezone.utc).isoformat(), confirmed_by=confirmed_by))` 后 `emit("post_command", {"command_id": command_id, "ordinal": len(self._document.commands) - 1})` → ⑨返回 result。
- **信号纪律**：pre_command/post_command 仅 record=True 路径发射（重放不是新命令执行，无审计信号；重放完成由 _rebuild 尾部的 geometry_rebuilt 统一通知）。写入历史与 geom 的 params 一律为 normalized 拷贝（`dict(normalized)`）。
### execute / undo / redo
- `execute`：`result = self._execute_one(command_id, params, confirmed_by, record=True)` 成功返回前 `self._redo_stack.clear()`；异常传播则 redo 栈不动（clear 在成功路径末尾）。
- `undo(self, n: int = 1) -> None`：先 `self._validate_n("undo", n)`；`n > len(self._document.commands)` → `raise InvalidHistoryError(f"undo: history has {len(self._document.commands)} commands, requested {n}")`（变更前抛出，原子）；`popped = self._document._pop_commands(n)`（执行序）；`self._redo_stack.extend(reversed(popped))`（栈顶=最近撤销）；`self._rebuild()`。
- `redo(self, n: int = 1) -> None`：对称——`_validate_n("redo", n)`；`n > len(self._redo_stack)` → InvalidHistoryError（同式）；`popped = self._redo_stack[-n:]`；`del self._redo_stack[-n:]`；`for cmd in reversed(popped): self._document._append_command(cmd)`（**追加原 ExecutedCommand 实例**，保留原 ordinal/timestamp_utc/confirmed_by/amendments）；`self._rebuild()`。
- `_validate_n(action, n)`：`if not isinstance(n, int) or n < 1: raise InvalidHistoryError(f"{action}: n must be an integer >= 1, got {n!r}")`。
### _rebuild
- `self._kernel.reset()` → 逐条 `self._execute_one(cmd.id, cmd.params, cmd.confirmed_by, record=False)`（normalize 幂等、validate 对已规范化形态幂等通过；不改写任何字段）→ 尾部 `self._document.events.emit("geometry_rebuilt")`（失败路径不发射）。
- 回放异常包装：`except GeometryBuildError as e: if e.ordinal is None: raise type(e)(str(e), ordinal=cmd.ordinal) from e; raise`；TopologyReferenceError 同式。ordinal 已有则原样透传。
### edit_and_replay
- `def edit_and_replay(self, ordinal: int, params: Mapping[str, object], actor: str, reason: str) -> None`：
  1. `commands_snapshot = copy.deepcopy(list(self._document.commands))`；`metadata_snapshot = self._document.metadata_snapshot()`。
  2. `self._document.replace_command_params(ordinal, params, actor, reason)`——校验失败（ValidationError/InvalidHistoryError/UnknownCommandError）直接传播，几何未动。
  3. `try: self._rebuild()` `except (GeometryBuildError, TopologyReferenceError) as original:` → `_restore_commands(commands_snapshot)` + `_restore_metadata(metadata_snapshot)` → `try: self._rebuild() except Exception as rb: raise ReplayDuringRollbackError(f"edit_and_replay rollback replay failed: {rb}", original=original, replay_reason=str(rb)) from rb` → 回滚成功后 `raise type(original)(str(original), ordinal=ordinal) from original`。
  4. 成功路径：`self._redo_stack.clear()`；**脏标记保持置位**（replace_command_params 已置脏；规格原文"清空 redo 栈、脏标记"按"置脏"语义执行——编辑=未保存变更；此解释写进 bus.py docstring）。geometry_rebuilt 已由 _rebuild 尾部发射，不重复。
### execute_batch
- `def execute_batch(self, plan: Plan) -> None`：
  1. `plan.mark_executing()`——**bus 不做前置 status 预检**，非法状态由 plan 状态机自身抛 InvalidPlanTransition（此时批未开始，无回滚）。
  2. `commands_snapshot = copy.deepcopy(list(self._document.commands))`；`metadata_snapshot = self._document.metadata_snapshot()`；`executed_ids: list[str] = []`。
  3. `for index, step in enumerate(plan.steps):` 循环体内 `try: self._execute_one(step.id, step.params, plan.confirmed_by, record=True); executed_ids.append(step.id)` `except Exception as exc:` → 恢复快照（_restore_commands + _restore_metadata）→ `try: self._rebuild() except Exception as rb: plan.mark_failed(); raise ReplayDuringRollbackError(f"batch rollback replay failed: {rb}", original=<下方先构造的 BatchRollbackError 实例>, replay_reason=str(rb)) from rb` → 回滚成功：`plan.mark_failed()` → `raise BatchRollbackError(f"batch failed at step {index} ({step.id}): {exc}", failed_ordinal=index, failed_command_id=step.id, reason=str(exc), executed_ids=tuple(executed_ids)) from exc`。**先状态转移后抛错**；failed_ordinal=批内 0-based 步序（evidence 由终验注明）；redo 栈在失败路径完全不动。
  4. 全部成功：`plan.mark_done()` → `self._redo_stack.clear()`（批内新命令成功 → 按"任何新命令成功执行都清空 redo 栈"清；失败路径已回滚故不动）→ return。
  - 二次失败路径的 original 构造：先建 `bre = BatchRollbackError(...同上四字段...)` 再 `raise ReplayDuringRollbackError(..., original=bre, replay_reason=str(rb)) from rb`（规格：original=BatchRollbackError，保留两者信息；TopologyReferenceError 的 ordinal 经 str(exc) 进 reason 链）。
### exceptions.py 授权扩展（仅两类，全部带默认值；其余 13 类与类间顺序禁触）
```python
@dataclass
class BatchRollbackError(MycadError):
    """A batch failed and was rolled back to its pre-batch state."""

    failed_ordinal: int = -1
    failed_command_id: str = ""
    reason: str = ""
    executed_ids: tuple[str, ...] = ()
```
```python
@dataclass
class ReplayDuringRollbackError(MycadError):
    """Replay was attempted while a rollback is in flight."""

    original: BaseException | None = None
    replay_reason: str = ""
```
（docstring 按上面修正；dataclass 字段全部默认值，位置构造兼容不破坏。）
### 测试夹具（test_bus.py 顶部定义）
- `FakeKernel`：`__init__(self)` 存 `applied: list[tuple[str, dict[str, object]]]`、`reset_count: int = 0`、`fail_when: Callable[[int, str, dict[str, object]], Exception] | None = None`、`_apply_total: int = 0`（reset 不清零）。`reset()`→`reset_count += 1; self.applied.clear()`。`apply(command_id, params)`→先 `n = self._apply_total; self._apply_total += 1`；`if self.fail_when is not None: exc = self.fail_when(n, command_id, dict(params)); if exc is not None: raise exc`；`self.applied.append((command_id, dict(params)))`。
- `FakeHandler`：`command_id = "demo.ping"`（实例属性，在 `__init__` 赋 `self.command_id`）；`handle(params, ctx)` 返回 `"pong"`。
- `EchoHandler`：`__init__(self, command_id: str)` 存 `self.command_id`；`handle(params, ctx)` 先 `assert ctx.command_id == self.command_id`，返回 `self.command_id`。
- registry 夹具（单一装配 helper，返回 `(registry, handlers, fake)`，各用例按需增删）：`reg = demo_registry()`（已注册 feature.cylinder）；再注册 demo.ping/demo.a/demo.b/demo.sel/demo.ghost 五个 CommandSpec（version=1、summary_en/label_zh 任意短串、`cli=CliSyntax((id,))`；除 demo.sel 外 params_schema 均为 `{"type": "object", "properties": {}, "additionalProperties": False}`）。handlers 映射 = `{"demo.ping": FakeHandler(), "demo.a": EchoHandler("demo.a"), "demo.b": EchoHandler("demo.b"), "demo.sel": EchoHandler("demo.sel"), "feature.cylinder": BuiltinModelingHandler("feature.cylinder")}`（`from mycad.core.handlers import BuiltinModelingHandler`）。**demo.ghost 故意不配 handler**——"有 spec 无 handler" → UnknownCommandError；"registry 无 spec" 用未注册 id "demo.nothing" → UnknownCommandError。
- normalization 专用 spec（装配 helper 已注册）：`CommandSpec(id="demo.sel", version=1, summary_en="sel", label_zh="选择器", params_schema={"type": "object", "properties": {"surface": {"type": "string", "enum": ["plane", "cylinder"]}, "axis": {"type": "string"}}, "required": ["surface"], "additionalProperties": False}, cli=CliSyntax(("demo.sel",)))`；执行 `bus.execute("demo.sel", {"surface": "cylinder", "axis": ""})` 后断言 `fake.applied[-1][1]` **不含 "axis" 键**（normalize 删键=规格"值为 None"的语义等价，断言键缺失；此解释写入测试注释）。
- Plan 夹具：`Plan(steps=[PlannedCommand(id="demo.a", version=1, params={}, summary_en="a", affected_object="box_body"), ...])` + `plan.confirm("cli-local")`。
- 状态序列观察：`monkeypatch.setattr(plan, "mark_executing", wrapper)`（wrapper 记录后调原方法；**禁止直接属性赋值** `plan.mark_executing = ...`——strict 下类型报错）。
### bus.py 分块（4 块 cat，总 ≤240 行）
- 块一：SPDX+docstring+imports+类头+`__init__`。**import 纪律（防包级循环导入，编排方 2026-10-05 复核修正，禁止改为顶层运行时 import）**：后续 T6d 会创建 `core/__init__.py`，而 commands/spec.py、registry.py 顶层 import `mycad.core.exceptions`——若 bus.py 顶层运行时 import 任何 mycad.commands 模块，将形成 `commands.validation(入口半初始化) → core.__init__ → bus → commands.validation` 炸弹。因此：①模块头 `from __future__ import annotations`；②`if TYPE_CHECKING:` 块内 `from mycad.commands.registry import CommandRegistry`（仅注解用）；③`validate_params`/`normalize_params` 在 `_execute_one` 方法体首行**函数内局部 import**（`from mycad.commands.validation import normalize_params, validate_params`；运行时调用时模块必已完整加载；ruff 规则集无 PLC0415）。其余顶层 imports：`copy`、`collections.abc.Mapping`、`datetime.datetime/timezone`、`mycad.core.document.Document/ExecutedCommand`、`mycad.core.exceptions` 五类、`mycad.core.handlers.CommandHandler/HandlerContext`、`mycad.core.kernel_protocol.Kernel`、`mycad.core.plan.Plan`。
- 块二：`execute` + `_execute_one`。
- 块三：`_validate_n` + `undo` + `redo` + `_rebuild`。
- 块四：`edit_and_replay` + `execute_batch`。

## 本片任务清单（预咀嚼，从 C0 顺序机械执行；禁止先写清单文件，每完成一步输出 DONE C<n>）
- C0：读参考（只读）：src/mycad/core/document.py（Document 内部 API）、src/mycad/core/plan.py、src/mycad/core/handlers.py、src/mycad/core/exceptions.py（两类现状）、src/mycad/commands/validation.py（normalize_params 行为）、src/mycad/commands/registry.py、src/mycad/commands/demo.py、tests/test_exceptions.py（确认只锁名单/数量/特定字段）。DONE C0。
- C1：改 src/mycad/core/exceptions.py（edit 精准替换两类：追加默认值字段+修 docstring）→ `uv run pytest tests/test_exceptions.py -q` 绿 + `uv run basedpyright src/mycad/core/exceptions.py` 0 errors。DONE C1。
- C2：写 tests/core/test_bus.py 第一批（≤85 行，cat >：夹具 FakeKernel/FakeHandler/EchoHandler/装配 helper + pong 透传且历史一条 + "有 spec 无 handler"（execute("demo.ghost", {})）→ UnknownCommandError + "registry 无 spec"（execute("demo.nothing", {})）→ UnknownCommandError + 分派锁定 demo.a/demo.b + EchoHandler 手工错配 ctx 断言触发 AssertionError（pytest.raises(AssertionError)，直接调 handler.handle(params, HandlerContext(kernel=fake, command_id="demo.b"))））。→ 红。DONE C2。
- C3：cat > src/mycad/core/bus.py 块一+块二（SPDX/imports/__init__/execute/_execute_one）→ C2 绿 + basedpyright bus.py 0 errors。DONE C3。
- C4：cat >> test_bus.py 第二批（≤85 行；本批夹具：先经 bus.execute 连续执行 4 次 feature.cylinder（params 各异，如 radius=1.0/2.0/3.0/4.0、height=1.0，confirmed_by=None），使 fake.applied 有 4 条记录、历史 4 条：execute 后 confirmed_by="cli-local" 落历史（单执行一次带该参断言）；省略 → None；undo 默认 n=1 弹 1 条（历史 3、redo 栈 1、fake.reset_count==1）；全新装配下 undo(3) 一次弹 3 条且恰一次 _rebuild（reset_count==1）且 applied==前 1 条重放序列；redo(2) 对称恢复（applied==全部 4 条按序重放、redo 栈空）；n=0/-1 → InvalidHistoryError；空历史 undo → InvalidHistoryError；空 redo 栈 redo → InvalidHistoryError；先 undo(1) 再 redo(99) → InvalidHistoryError 且 fake.reset_count/applied/历史长度/`len(bus._redo_stack)` 全部与 redo(99) 调用前一致；undo 后 execute 新命令 → redo 栈被清空（再 redo → InvalidHistoryError））。→ 红。DONE C4。
- C5：cat >> bus.py 块三（_validate_n/undo/redo/_rebuild）→ C4 绿。DONE C5。
- C6：cat >> test_bus.py 第三批（≤85 行，edit_and_replay 四场景，文档夹具：Document(demo_registry 变体, commands=[手工 ExecutedCommand(feature.cylinder...), 手工 ExecutedCommand(feature.cylinder...)]，ordinal 0/1；场景①fake 无失败，编辑第 0 条 radius→3.0：重放后 fake.applied[0] 参数为新值、document.commands[0].amendments 长 1 含 from_params=旧 params、timestamp_utc 字符串前后相等、command_amended 信号恰一次（document.events.subscribe 计数）；②radius=-1.0 → ValidationError 且 commands/amendments/信号计数/applied 全不变；③fail_when=lambda n,cid,p: GeometryBuildError("boom") if p.get("radius")==99.0 else None，编辑 radius→99.0 → 抛 GeometryBuildError 且 e.ordinal==0、commands[0].params/amendments 回滚为旧值、applied 回到编辑前两步序列；④fail_when=lambda n,cid,p: GeometryBuildError("dead") if n>=1 else None（手工历史不产生 apply；编辑后 _rebuild 重放 n=0 过、n=1 败；回滚 _rebuild 重放 n=2 败）→ ReplayDuringRollbackError 且 e.original 为 GeometryBuildError、e.replay_reason 非空）。→ 红。DONE C6。
- C7：cat >> bus.py 块四（edit_and_replay+execute_batch）→ C6 绿 + basedpyright bus.py 0 errors。DONE C7。
- C8：cat >> test_bus.py 第四批（≤90 行，execute_batch。批前文档均用新 Document（空历史），场景⑤除外；批步骤用 PlannedCommand(id=..., version=1, params=..., summary_en=..., affected_object="box_body")，demo.a/demo.b 的 params={}，feature.cylinder 的合法 params={"radius": 1.0, "height": 2.0}：①成功批 3 步（demo.a/demo.b/demo.a）→ plan.status=="done"、monkeypatch.setattr 包装 mark_executing/mark_done 各记录一次、历史 +3 且每条 confirmed_by=="cli-local"、参数化第二例 actor="acceptance-test" 批内每条 confirmed_by==plan.confirmed_by=="acceptance-test"；②失败场景 A 第 2 步 validate 失败（步骤 demo.a/demo.b 后接 feature.cylinder 且其 params={"radius": -1.0, "height": 2.0}；feature.cylinder 在 handlers 中有 BuiltinModelingHandler，流水线走 handler 检查后 validate 抛 ValidationError）→ BatchRollbackError 四字段（failed_ordinal==1、failed_command_id=="feature.cylinder"、reason 非空含校验信息、executed_ids==("demo.a",)）、历史回到批前（长度 0）、fake.applied 为空（第 2 步未到 kernel）、plan.status=="failed"；③失败场景 B 第 3 步几何失败（步骤 demo.a/demo.b/feature.cylinder 合法 params，fail_when=lambda n,cid,p: GeometryBuildError("kernel boom") if cid=="feature.cylinder" else None）→ 同上四字段断言（failed_ordinal==2、failed_command_id=="feature.cylinder"、executed_ids==("demo.a","demo.b")）、fake.applied 回到批前空序列（回滚 _rebuild 重放空历史）、plan.status=="failed"；④draft plan（未 confirm）→ InvalidPlanTransition 且历史/几何未动；done plan（confirm 后手工 mark_executing/mark_done 或复用①后 plan）→ InvalidPlanTransition；⑤二次失败：批前历史先放 1 条手工 ExecutedCommand(id="feature.cylinder", version=1, params={"radius":1.0,"height":2.0}, ordinal=0, timestamp_utc="2026-01-01T00:00:00+00:00", confirmed_by=None)（经 Document(reg, commands=[...]) 构造；注意 demo.a/demo.b 步骤经 EchoHandler 不产生 kernel apply，故本场景批步骤改用 feature.cylinder 使 FakeKernel 计数生效），批 2 步均 PlannedCommand(id="feature.cylinder", params={"radius":1.0,"height":2.0},...)，fail_when=lambda n,cid,p: GeometryBuildError("dead") if n>=1 else None（step1 apply n=0 ✓、step2 apply n=1 抛；回滚 _rebuild 重放那 1 条历史命令 n=2 再抛）→ ReplayDuringRollbackError 且 isinstance(e.original, BatchRollbackError)、e.replay_reason 非空、plan.status=="failed"）。→ 红。DONE C8。
- C9：跑 `uv run pytest tests/core/test_bus.py -q` 至 C8 全绿。DONE C9。
- C10：cat >> test_bus.py 第五批（≤40 行，规范化：①demo.sel 用例断言 fake.applied[-1][1] 不含 "axis" 键（注释注明删键=规格 None 语义等价）；②旁路 grep：`ROOT = Path(__file__).resolve().parents[2]`，遍历 `(ROOT/"src"/"mycad"/"geom").glob("*.py")` 断言每文件文本不含 "normalize_params"；遍历 `(ROOT/"src").rglob("*.py")` 断言含 "normalize_params" 的文件路径集合 ⊆ {"src/mycad/commands/validation.py", "src/mycad/core/bus.py"}——用相对路径 str(p.relative_to(ROOT)) 比较）。→ 红（bus.py 已有则直接绿，两种均可接受）。DONE C10。
- C11（终验）：下方 scoped 命令全跑全绿。DONE C11。
- C12：回合输出 DoneClaim JSON 结束。

## 本片 scoped 验证命令（终验 C11 全跑）
- uv run pytest tests/core/test_bus.py tests/core/test_document.py tests/core/test_handlers.py tests/core/test_kernel_protocol.py tests/test_exceptions.py -q 全绿
- uv run basedpyright src/mycad/core/bus.py src/mycad/core/exceptions.py tests/core/test_bus.py → 0 errors, 0 warnings
- uv run ruff check src/mycad/core/bus.py src/mycad/core/exceptions.py tests/core/test_bus.py
- uv run ruff format --check src/mycad/core/bus.py src/mycad/core/exceptions.py tests/core/test_bus.py

## DoneClaim（结尾必须输出）
{"task":"T6c","changed_files":[...],"tests":[命令+尾部结果],"risks":[...]}
