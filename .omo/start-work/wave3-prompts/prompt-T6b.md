# T6b — MyCAD core 之 Document 类（T6 拆分 3：追加 Document 本体到 a2 交付的 document.py DTO 半区）

你是本仓库的实现代理。工作目录 /media/sima/Data/projects/MyCAD。本提示词与计划规格是唯一权威，逐字机械执行，零发明权。

## 前置磁盘现状（编排方已核实，直接采信）
- `src/mycad/core/document.py` 已由前置片交付 **DTO 半区**：ExecutedCommand/CommandAmendment/AffectedObject/AFFECTED_OBJECTS/PlannedCommand，文件尾有占位注释 `# T6b: Document 类在此追加`。你只在此追加 Document 类。
- `src/mycad/core/groups.py`（NamedGroup frozen，list 自动 tuple 化）、`src/mycad/core/signals.py`（SignalName 九值 + SignalBus：subscribe/emit，payload 缺省投递 {}）、`src/mycad/core/plan.py`（Plan 状态机）均已交付且绿 → 只读。
- `src/mycad/core/kernel_protocol.py`、`handlers.py`、`ports.py` 已交付（协议片）→ 只读。
- `src/mycad/core/exceptions.py`：15 类闭合，MycadError 基类字段 `message: str; command_id: str | None = None` → **本片禁改**。
- T3 夹具：`src/mycad/commands/demo.py` 有 `demo_registry()`（注册 feature.cylinder，radius/height 为 Positive 即 exclusiveMinimum 0）与 `cylinder_spec()`；`CommandRegistry(schema_defs)`/`.register`/`.get(id, version=None)`/`.schema_defs`；`validate_params(spec, params, defs)`/`normalize_params(params)` 在 `src/mycad/commands/validation.py`。

## 反停摆硬纪律（历史上 9 个代理死于长单回合生成，违反即死）
1. 开工第一动作：直接执行下方『任务清单』的步骤 B0。**禁止先写任何清单/计划/总结文件**；每完成一步，回合文字里输出 `DONE B<n>` 即可。
2. 单次文件写入硬上限 ~100 行。首块 `cat > file` ≤100 行，续写一律 `cat >> file` 追加。
3. 每回合恰一个小动作：写一个文件块 / 跑一条 scoped 验证 / 读一个参考文件。三选一。
4. 禁止长篇设计推理——设计已在规格中写死，你只做机械转写。回合内文字输出保持极短。
5. 遇范围外阻塞立即输出 `BLOCKED: <原因>` 结束，勿空转。

## 通用规则
- SPDX 两行头参照 src/mycad/core/exceptions.py（document.py 已有，禁重复）。
- basedpyright strict 零逃逸：禁 type: ignore / pyright: ignore。
- TDD 垂直切片：先追加测试（红）→ 追加实现块 → scoped 验证（绿）→ 下一片。
- 验证一律路径级 scoped 命令，禁全量套件。
- 禁止 git add/commit/stash 任何操作。
- 参考实现（只读，禁改）：src/mycad/core/exceptions.py、src/mycad/core/groups.py、src/mycad/core/signals.py、src/mycad/commands/demo.py、src/mycad/commands/registry.py、src/mycad/commands/validation.py。

## 本片范围（白名单，越界即违规）
追加（仅 cat >>，**禁改 DTO 半区已有内容**）：
- src/mycad/core/document.py（Document 类，追加在占位注释处，≤150 行，分块写）
新建：
- tests/core/test_document.py
禁触：src/mycad/core/ 其他一切文件（exceptions/signals/groups/plan/kernel_protocol/handlers/ports）、src/mycad/geom/、src/mycad/commands/、tests/geom/、tests/commands/、既有全部测试文件（只读）；bus.py/persistence.py/schema_v1.py/migrations/（本片不创建）；.omo/evidence/（归后续片）。

## 规格原文（计划 .omo/plans/phase0-mvp.md T6 段逐字节选，唯一权威）
  - `Document`：metadata v1 **封顶六键**（必填 part_no/revision/material/source 四个字符串 + 可选 part_name/notes 两个字符串；任何其他键由校验层抛 ValidationError，PLM 自定义属性留给未来 schema 版本）；**`new` 文档的 metadata 初值写死**：`part_no=""`、`revision=""`、`material=""`、`source="local"`、无 part_name/notes 键（空字符串是合法值，保证文本脚本路径不写 meta 也能存档）；有序 `list[ExecutedCommand]`；named_groups: dict[str, NamedGroup]（CAE 缝：名称+谓词描述子列表，阶段 0 可手工增删、随存档序列化，**不进几何重放序列、不触发 _rebuild**，与 metadata 同为文档注释态）；脏标记；`events` 经信号总线发出。
  - **历史参数编辑 API（#10，唯一入口）**：`Document.replace_command_params(ordinal: int, params: Mapping[str, object], actor: str, reason: str) -> ExecutedCommand`——①经 `self._registry` 取该命令 spec 并以 `validate_params(spec, params, defs=self._registry.schema_defs)` 重新校验（#round11-2：Document 构造即持有 registry；不合法抛 ValidationError，文档不变）；②深拷贝当前命令列表为快照；③替换该 ordinal 的 params 并追加 CommandAmendment（at=UTC ISO8601、from_params=旧参数），**保留原 ordinal/timestamp_utc/confirmed_by 不变**；④发 pre_command/post_command 之外的专用信号 `command_amended`；⑤返回修订后的 ExecutedCommand。几何重放由 Bus 侧方法负责，Document 本方法不改几何。
  - **`Document.set_metadata(key: str, value: str)`（#6 文本路径元数据；唯一入口）**：key 必须 ∈ {part_no,revision,material,source,part_name,notes} 六白名单，未知键 ValidationError；value 必须是字符串；直接改 metadata、置脏、发 `metadata_changed` 信号；**不进命令历史、不参与重放、无 undo 条目**（阶段 0 的元数据是文档属性不是建模命令；save 后随存档持久化）。
  - groups Document API：`add_named_group(group: NamedGroup) -> None`（重名→ValidationError，发 `named_group_added` 信号）、`remove_named_group(name: str) -> None`（不存在→KeyError 由 T10 归运行错误 1，发 `named_group_removed`）；name 非空字符串由 Document API 校验。
  - Must NOT do：不 import geom/formats；不做并发写锁（单线程文档模型，类 docstring 注明）；ExecutedCommand/PlannedCommand/AFFECTED_OBJECTS 不在 core 外重复定义。

## 编排方钉死的设计（唯一自由度已收敛，逐条照抄）
- 构造签名：`def __init__(self, registry: CommandRegistry, *, metadata: Mapping[str, str] | None = None, commands: Iterable[ExecutedCommand] | None = None, named_groups: Mapping[str, NamedGroup] | None = None) -> None`。
- 模块级常量 `METADATA_KEYS = ("part_no", "revision", "material", "source", "part_name", "notes")`；`DEFAULT_METADATA = {"part_no": "", "revision": "", "material": "", "source": "local"}`。
- `metadata=None` → 拷贝 DEFAULT_METADATA；显式传入 → 逐键 ∈ METADATA_KEYS（未知键 ValidationError），内部持私有 dict 拷贝。公开 `metadata` property 返回 `dict[str, str]` 拷贝。
- `self._registry = registry`。**import 纪律（防包级循环导入，编排方 2026-10-05 复核修正，禁止改为顶层运行时 import）**：后续 T6d 会创建 `core/__init__.py`（import 全部 core 子模块），而 commands/spec.py、registry.py 顶层 import `mycad.core.exceptions`——若 document.py 顶层运行时 import 任何 mycad.commands 模块，将形成 `commands.spec → core.__init__ → document → commands.registry → commands.spec(半初始化)` 炸弹。因此：①模块头必须 `from __future__ import annotations`；②`if TYPE_CHECKING: from mycad.commands.registry import CommandRegistry`（仅注解用）；③replace_command_params 内的 `validate_params` 用**函数内局部 import**（`from mycad.commands.validation import validate_params`，写在方法体首行；ruff 规则集无 PLC0415，不会报错）。
- `self.events = SignalBus()`（from mycad.core.signals）。
- 脏标记：`_dirty: bool` 初始 False；公开 `is_dirty` property + `mark_clean() -> None`；一切变更操作（set_metadata/组增删/replace_command_params/_append_command/_pop_commands/_restore_commands/_restore_metadata）置 True。
- 历史容器：`_commands: list[ExecutedCommand]`；公开 `commands` property 返回 `tuple[ExecutedCommand, ...]`。
- Bus 面内部 API（后续片 T6c 消费，下划线约定）：`_append_command(command: ExecutedCommand) -> None`、`_pop_commands(n: int) -> list[ExecutedCommand]`（弹末尾 n 条）、`_restore_commands(snapshot: list[ExecutedCommand]) -> None`（整体替换）。
- metadata 快照面（T6c 批回滚用）：`metadata_snapshot() -> dict[str, str]`（深拷贝）+ `_restore_metadata(snapshot: Mapping[str, str]) -> None`。
- `set_metadata`：key 非白名单或 value 非 str → ValidationError；成功后 `self.events.emit("metadata_changed", {"key": key, "value": value})`。
- `named_groups` 公开只读 property 返回 `dict[str, NamedGroup]` 拷贝；`add_named_group`：`group.name` 非空 str（空串/非 str → ValidationError）→ 重名（name 已在）→ ValidationError → 存入 → `emit("named_group_added", {"name": group.name})`；`remove_named_group`：缺失 → `raise KeyError(name)` → 删除 → `emit("named_group_removed", {"name": name})`。
- `replace_command_params`：ordinal 不在 `[0, len(self._commands))` → `InvalidHistoryError(f"ordinal {ordinal} not in history")`；`self._registry.get(command.id)` 抛 UnknownCommandError 时原样传播；validate_params 不通过 → ValidationError 且文档零变更（校验先于一切变更）；**不做 normalize_params**（规范化唯一调用点=Bus，#round11-2）；成功路径：`new_cmd = dataclasses.replace(cmd, params=dict(params), amendments=cmd.amendments + (CommandAmendment(at=datetime.now(timezone.utc).isoformat(), actor=actor, from_params=dict(cmd.params), reason=reason),))`，替换列表槽位，`emit("command_amended", {"ordinal": ordinal, "command_id": cmd.id})`，返回 new_cmd，置脏。深拷贝快照用 `copy.deepcopy`（规格②的字面要求，防御性）。
- 类 docstring 注明：单线程文档模型（无并发写锁，规格 Must NOT do）。

## 本片任务清单（预咀嚼，从 B0 顺序机械执行；禁止先写清单文件，每完成一步输出 DONE B<n>）
- B0：读参考（一回合内 cat）：src/mycad/core/document.py（DTO 半区+占位注释）、src/mycad/core/signals.py（SignalBus API）、src/mycad/core/groups.py、src/mycad/commands/demo.py（demo_registry 夹具）。DONE B0。
- B1：写 tests/core/test_document.py 第一批（≤80 行，cat >）：new 文档 metadata 初值四键且无 part_name/notes；set_metadata 六白名单逐一合法（参数化）；第七键 ValidationError；value 非 str ValidationError；每次 set_metadata 恰触发一次 metadata_changed（订阅计数）；is_dirty 置位与 mark_clean 复位；构造显式传未知 metadata 键 ValidationError。→ pytest 红。DONE B1（测试红即完成）。
- B2：cat >> src/mycad/core/document.py 追加 Document 块一（≤60 行：类头+docstring+__init__+METADATA_KEYS/DEFAULT_METADATA+metadata property+set_metadata+is_dirty/mark_clean）→ B1 测试绿 + basedpyright document.py 0 errors。DONE B2。
- B3：cat >> tests/core/test_document.py 第二批（≤60 行）：add_named_group 正常入组+named_group_added 恰一次；重名 ValidationError；name 空串/非 str ValidationError；remove 正常+named_group_removed 恰一次；remove 不存在 KeyError；named_groups property 与 add/remove 联动。→ 红。DONE B3。
- B4：cat >> document.py 块二（≤50 行：named_groups property+add_named_group+remove_named_group+metadata_snapshot/_restore_metadata）→ B3 绿。DONE B4。
- B5：cat >> tests/core/test_document.py 第三批（≤80 行，夹具用 demo_registry() + 手工 ExecutedCommand(id="feature.cylinder", version=1, params={"radius":1.0,"height":2.0}, ordinal=0, timestamp_utc="2026-01-01T00:00:00+00:00", confirmed_by=None) 传入 Document(reg, commands=[...])）：合法修订（params={"radius":3.0,"height":2.0}）→ 返回实例 amendments 恰 1 条含 from_params==旧 params、ordinal/timestamp_utc/confirmed_by/id/version 不变、document.commands 槽位已替换、is_dirty 置位、command_amended 恰触发一次；非法 params（radius=-1.0）→ ValidationError 且 commands/amendments/信号计数全部不变；ordinal 越界（5）→ InvalidHistoryError。→ 红。DONE B5。
- B6：cat >> document.py 块三（≤60 行：commands property+replace_command_params+_append_command/_pop_commands/_restore_commands）→ B5 绿。DONE B6。
- B7（终验）：下方命令全跑全绿。DONE B7。
- B8：回合输出 DoneClaim JSON 结束。

## 本片 scoped 验证命令（终验 B7 全跑）
- uv run pytest tests/core/test_document.py tests/core/test_document_dtos.py tests/core/test_groups.py tests/core/test_signals.py -q 全绿
- uv run basedpyright src/mycad/core/document.py tests/core/test_document.py → 0 errors, 0 warnings
- uv run ruff check src/mycad/core/document.py tests/core/test_document.py
- uv run ruff format --check src/mycad/core/document.py tests/core/test_document.py

## DoneClaim（结尾必须输出）
{"task":"T6b","changed_files":[...],"tests":[命令+尾部结果],"risks":[...]}
