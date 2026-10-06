# T6a2 — MyCAD core 契约层之 DTO/状态机片（T6 拆分 2/2：groups + signals + document DTO + plan）

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
- src/mycad/core/groups.py（NamedGroup）
- src/mycad/core/signals.py（九信号总线）
- src/mycad/core/document.py（**仅 DTO 层**：ExecutedCommand/CommandAmendment/AffectedObject Literal/AFFECTED_OBJECTS 常量/PlannedCommand——Document 类/replace_command_params/set_metadata 属 T6b 禁写；文件尾留 `# T6b: Document 类在此追加` 占位注释）
- src/mycad/core/plan.py（Plan/PlanStatus 状态机）
- tests/core/test_groups.py、tests/core/test_signals.py、tests/core/test_document_dtos.py、tests/core/test_plan_state_machine.py
- tests/typing/expect_errors.py
- .omo/evidence/task-6-phase0-mvp.md（创建并写 §T6a：T6a1+T6a2 两子片交付清单/验证输出尾部/偏离记录；注明 T6a1 验证由编排方复跑）
禁触：src/mycad/geom/、src/mycad/commands/、tests/geom/、tests/commands/；src/mycad/core/kernel_protocol.py、handlers.py、ports.py 及其测试（并行兄弟 T6a1 所有——只读不写）；bus.py/persistence.py/schema_v1.py（本片不创建）；既有 tests/core/test_selectors.py 只读保持绿。

## 规格原文（计划 .omo/plans/phase0-mvp.md 306-349 行逐字节选，唯一权威）
（注意：本片为 T6 拆分之二。规格全文还包含 kernel_protocol/handlers/ports（兄弟片 T6a1 并行）与 bus.py/persistence.py/Document 类/集成测试大段（T6b/T6c）——均不在本片范围。下方仅收录对本片有约束力的段落。）

  - `document.py`（**核心 DTO 在此唯一定义，全包只准从本模块 import，禁止第二处重复定义**）：
    - `ExecutedCommand` frozen dataclass **恰好六审计字段**：`id: str, version: int, params: dict[str, object], ordinal: int, timestamp_utc: str, confirmed_by: str | None`；外加可选修订留痕 `amendments: tuple[CommandAmendment, ...] = ()`（`CommandAmendment(at: str, actor: str, from_params: dict[str, object], reason: str)`；初始命令该元组为空，不计入"六字段"计数——存档中无修订时不出现 amendments 键）。
    - **`AffectedObject = Literal["box_body", "cylinder_body", "extruded_body", "revolved_body", "hole", "hole_pattern", "edge", "tool_body"]`**（模块级 Literal，八字面量与 B.2 逐字一致）；`PlannedCommand` frozen dataclass：`id: str, version: int, params: dict[str, object], summary_en: str, affected_object: AffectedObject`（**summary_en 唯一来源（#round8-4）：计划加载器/CLI 批构造在 registry.get(id) 命中后从 spec.summary_en 复制，禁止来自计划文件——B.1 step 恰好四键（id/version/params/affected_object），显式包含 summary_en 经 additionalProperties:false 拒绝；构造顺序=先查 registry（未知 id 此时即 UnknownCommandError，早于 summary 复制）→复制 summary_en→查 B.2 affected_object；测试：解析出的每条 PlannedCommand.summary_en == registry.get(id).summary_en、计划 step 多给 summary_en→ValidationError、未知 step id→UnknownCommandError**；**静态类型即锁定八字面量**：传表外字符串 basedpyright 报错；构造时另做运行时 `AFFECTED_OBJECTS` 查表（常量见下，与 Literal 同源断言防漂移），查不到 id→UnknownCommandError；静态与运行时双门）；Plan.steps 是它的列表。**静态失败测试方式写死**：`tests/typing/expect_errors.py`（basedpyright 扫描该目录、pytest 经 T1 addopts 排除收集，#round11-6）含一行 `PlannedCommand(..., affected_object="bogus")  # pyright: ignore[reportArgumentType]` 对照——正向文件无 ignore 赋值合法八字面量；另用 `assert_never`/`typing.get_args(AffectedObject)` 断言 `get_args` 返回元组恰为八字面量且与 `set(AFFECTED_OBJECTS.values())` 相等。

  - **`src/mycad/core/groups.py`（NamedGroup 契约，#10；描述子数据类已由 T1 落在 core/selectors.py，故 core 内自洽、无 geom 依赖）**：`@dataclass(frozen=True) NamedGroup(name: str, faces: tuple[FaceSelector, ...] = (), edges: tuple[EdgeSelector, ...] = ())`（从 mycad.core.selectors import 两描述子；name 非空字符串由 Document API 校验；构造时 faces/edges 接收 list 则内部 tuple() 化）。Document API：`add_named_group(group: NamedGroup) -> None`（重名→ValidationError，发 `named_group_added` 信号）、`remove_named_group(name: str) -> None`（不存在→KeyError 由 T10 归运行错误 1，发 `named_group_removed`）；信号 Literal 清单相应扩为 pre_command/post_command/command_amended/metadata_changed/named_group_added/named_group_removed/document_saving/document_saved/geometry_rebuilt。

  - `signals.py`：极简 headless 信号（标准库：订阅 list + 弱引用；**事件类型 Literal 恰好九个（与 groups.py 段的清单逐字一致，本清单是唯一权威）**：`pre_command`/`post_command`/`command_amended`/`metadata_changed`/`named_group_added`/`named_group_removed`/`document_saving`/`document_saved`/`geometry_rebuilt`；测试用 `typing.get_args(SignalName)` 锁定九元组与上述顺序逐字相等，并对 metadata_changed、named_group_added、named_group_removed 各做一次真实触发订阅断言（set_metadata/add_named_group/remove_named_group 各恰好触发一次）；回调异常隔离：一个监听器异常只 warning 不影响其他监听器与主流程——为插件隔离 T9 预埋）。**零 Qt 依赖**。

  - `plan.py`（放 core 由 agent 再导出）：`Plan(steps: list[PlannedCommand], status: PlanStatus = "draft", plan_id: str = field(default_factory=lambda: uuid.uuid4().hex), confirmed_by: str | None = None)`（**#round11-4：status 默认值写死 "draft" 且字段序 steps 在前——CLI begin-batch/run --json 的 `Plan(steps)` 构造形式即合法，类型测试锁定字段序与默认值**；plan_id 缺省自动生成 32 位小写 hex；CLI 读计划 JSON 缺 plan_id 时同样走 `uuid.uuid4().hex`，不得用时间戳格式；构造后 plan_id 只读）+ 纯函数转移 `confirm(actor)/mark_executing()/mark_done()/mark_failed()/cancel()`；`PlanStatus` Literal 六态 `draft|confirmed|executing|done|failed|cancelled`；**合法转移恰好 6 条边（本表是唯一权威，禁止"11 边"表述）**：①draft→confirmed（confirm(actor)，必须记录非空 confirmed_by，对空 actor 抛 ValueError）②draft→cancelled ③confirmed→executing ④confirmed→cancelled ⑤executing→done ⑥executing→failed；done/failed/cancelled 为终态。**非法转移表（参数化测试穷举）**：3 终态×6 请求动作全部拒绝；另测 draft→executing、draft→done、draft→failed、confirmed→done、confirmed→failed、executing→confirmed/cancelled 共 8 个跨态跳跃拒绝；非法转移一律抛 T1 清单中的 `InvalidPlanTransition(from_status, requested)`；**没有任何 LLM/网络代码**。

  - Must NOT do：不 import geom/formats（双依赖倒置，只持 Protocol）；不做 inverse 命令；不做 BREP 内嵌/快照缓存（ADR-002 演进口）；不做 Redo 以外的多分支历史；不引第三方事件库；不做并发写锁（单线程文档模型，文档注明）；**execute_batch 不允许"返回错误对象/部分成功"语义**；ExecutedCommand/PlannedCommand/AFFECTED_OBJECTS 不在 core 外重复定义。

## 本片任务清单（已预咀嚼，从步骤 0 直接顺序机械执行；每步内部"先测试（红）→后实现→scoped 验证（绿）"；禁止先写任何清单文件，每完成一步回合文字输出 DONE <n>）
- 步骤 0：写 tests/core/test_groups.py（NamedGroup frozen；faces/edges 传 list 内部 tuple 化；name/faces/edges 字段断言）。
- 步骤 1：写 src/mycad/core/groups.py（≤40 行）→ 步骤 0 测试绿。DONE 1。
- 步骤 2：写 tests/core/test_signals.py（typing.get_args(SignalName) 锁九元组**顺序**逐字相等；emit 触发计数；一个监听器抛错另一个照常收到且主流程不受影响）。
- 步骤 3：写 src/mycad/core/signals.py（≤90 行；超限分 cat > / cat >> 两次）→ 步骤 2 测试绿。DONE 3。
- 步骤 4：写 tests/core/test_document_dtos.py（get_args(AffectedObject) 八元组 == set(AFFECTED_OBJECTS.values())；表外字符串运行时查表 UnknownCommandError；ExecutedCommand/PlannedCommand frozen；amendments 默认空元组；len(dataclasses.fields(ExecutedCommand))==6）。
- 步骤 5：写 src/mycad/core/document.py 第一半（≤70 行：ExecutedCommand+CommandAmendment+T6b 占位注释）→ cat >> 第二半（≤80 行：AffectedObject+AFFECTED_OBJECTS+PlannedCommand）→ 步骤 4 测试绿 + basedpyright src/mycad/core/document.py 0 errors。DONE 5。
- 步骤 6：写 tests/typing/expect_errors.py（正向：PlannedCommand 合法八字面量赋值无 ignore；负向：一行 affected_object="bogus" 带 `# pyright: ignore[reportArgumentType]`）→ uv run basedpyright tests/typing 0 errors。DONE 6。
- 步骤 7：写 tests/core/test_plan_state_machine.py（6 合法边逐边各 1 例；3 终态×6 动作参数化拒绝；8 跨态跳跃拒绝；confirm("") ValueError；Plan(steps) 构造合法且 status=="draft"、plan_id 32 位小写 hex；字段序 steps 在前锁定）。
- 步骤 8：写 src/mycad/core/plan.py（≤110 行；超限分两次写）→ 步骤 7 测试绿。DONE 8。
- 步骤 9（终验）：下方命令全跑全绿。
- 步骤 10：写 .omo/evidence/task-6-phase0-mvp.md §T6a → 回合输出 DoneClaim JSON 结束。

## 本片 scoped 验证命令（终验步骤全跑）
- uv run pytest tests/core/test_groups.py tests/core/test_signals.py tests/core/test_document_dtos.py tests/core/test_plan_state_machine.py tests/core/test_selectors.py -q 全绿（若某自身文件尚未创建即报错——不应发生）
- uv run basedpyright src/mycad/core/groups.py src/mycad/core/signals.py src/mycad/core/document.py src/mycad/core/plan.py tests/core tests/typing → 0 errors, 0 warnings
- uv run ruff check src/mycad/core/groups.py src/mycad/core/signals.py src/mycad/core/document.py src/mycad/core/plan.py tests/core tests/typing
- uv run ruff format --check src/mycad/core/groups.py src/mycad/core/signals.py src/mycad/core/document.py src/mycad/core/plan.py tests/core tests/typing

## DoneClaim（结尾必须输出）
{"task":"<片名>","changed_files":[...],"tests":[命令+尾部结果],"risks":[...]}
