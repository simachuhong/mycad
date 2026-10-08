# T10b 任务书：run --json 计划执行 + validate + history --json + 文本⇄JSON 等价

你是 MyCAD 项目 T10b 片的执行代理。**点火已完成 cat 本文件。按 §5 清单机械执行，禁重新设计。前置：T10a 已交付并采信（cli 包骨架/REPL/内建命令/批状态机/tests/cli 四文件在盘）。**

## 0. 反停摆五纪律（违反=任务失败）

1. 禁写清单外文件；2. 单文件一次写 ≤100 行（cat > 首块 / cat >> 追加）；3. 每回合一个小动作；4. 禁长推理——设计已钉死；5. 遇阻输出 `BLOCKED: <原因>` 结束回合。

## 1. 白名单（仅允许创建/修改）

- 新建 `src/mycad/cli/plans.py`
- 修改 `src/mycad/cli/__main__.py`（仅：run 分支加 `--json` flag 判定 + 新增 `validate` 子命令分发）
- 修改 `src/mycad/cli/session.py`（仅：追加 `run_json`/`validate_file` 方法与 `history` 的 `--json` 分支；**允许**在模块顶部提取 ≤3 个共享 helper（如 `_BUILTIN_VERBS` frozenset、`_parse_modeling(line, registry)`）供 execute_line 与校验路径共用——**禁改 execute_line 既有语义**，tests/cli 既有测试全绿为准）
- 新建 `tests/cli/{test_run_json.py,test_validate.py,test_history.py}`
- 追加 `.omo/evidence/task-10-phase0-mvp.md` §T10b
- **禁改**：src/mycad 其他一切、tests/cli 既有四文件（test_repl/test_builtin/test_batch 只读，若 helper 提取导致失败→修 helper 不修测试）；禁 git。

## 2. 上下文（勿重复勘察）

- 计划原文：`sed -n '429,463p'`（T10 规格）+ `sed -n '660,740p'`（附录 B.1 计划 schema / B.2 映射 / B.3 run --json 语义）——A0 必读，B.1/B.3 逐字为准。
- **依赖面 API**（T10a 已核实）：`parse_line(text, registry) -> (id, params)`；`validate_params(spec, params, defs=registry.schema_defs)`；`AFFECTED_OBJECTS`（core/document.py 唯一权威）；`PlannedCommand(id, version, params, summary_en, affected_object)`；`Plan(steps)`→`.confirm(actor="cli-local")`；`bus.execute_batch(plan)`（BatchRollbackError 含 failed_ordinal/failed_command_id/executed_ids）；`save_document(document, path)`；`Document.set_metadata`（未知键 ValidationError）；`METADATA_KEYS`/`DEFAULT_METADATA`（四键 part_no:""/revision:""/material:""/source:"local"——**无 part_name/notes**）；`to_cli(id, params, registry)`（canonical 含 default 填充键）；`new_document(services)`；`uuid.uuid4().hex`。
- pytest 用 `.venv/bin/python -m pytest`。

## 3. 钉死设计

### 3.1 plans.py（B.1 校验器，run --json 与 validate .json 共用同一函数）

- `@dataclass(frozen=True) class ValidatedPlan:` 字段 `plan_id: str`、`plan_metadata: dict[str, str]`（恰计划中出现的键）、`steps: tuple[PlannedCommand, ...]`、`outputs: tuple[Path, Path, Path]`？——**钉死** `outputs: Outputs` 其中 `@dataclass(frozen=True) class Outputs:` `step: Path | None`、`stl: Path | None`、`archive: Path | None`（相对路径已 resolve 相对计划文件目录）。
- `def validate_plan_dict(data: object, registry: CommandRegistry, *, base_dir: Path) -> ValidatedPlan:`（data=json.loads 结果）：
  1. 非 dict→ValidationError `plan: expected object`。
  2. 顶层键必须 ⊆ {plan_id, metadata, steps, outputs}；metadata/steps 缺失→ValidationError；未知顶层键→ValidationError（消息含键名）。
  3. plan_id 存在时必须匹配 `^[0-9a-f]{32}$` 否则 ValidationError；缺省→`uuid.uuid4().hex`。
  4. metadata：dict；键必须 ⊆ 六白名单（part_no/revision/material/source 必填 + part_name/notes 可选）；值全 str（空串允许）；未知键→ValidationError。
  5. steps：list 且 minItems≥1；元素恰四键 id/version/params/affected_object；id 必须 registry 可解析（`registry.get(id)` 未知→`UnknownCommandError(identifier=id)`）；version 必须==spec.version；params 过 `validate_params(spec, params, defs=registry.schema_defs)`（ValidationError 传播）；affected_object 必须==`AFFECTED_OBJECTS[id]` 否则 ValidationError（消息含期望/实际）。
  6. outputs：dict；键 ⊆ {step, stl, archive}；值全 str 非空；相对路径 `(base_dir / value)` resolve；**archive 键也必须 .mc.json 扩展名否则 ValidationError**。
  7. 成功→ValidatedPlan（steps 为 PlannedCommand 元组，summary_en=spec.summary_en）。
- `def load_plan_file(path: Path, registry: CommandRegistry) -> ValidatedPlan:` 读文件→json.loads（JSONDecodeError→ValidationError `invalid JSON: ...`）→validate_plan_dict(data, registry, base_dir=path.parent)。

### 3.2 session.run_json（B.3 六步，argv ["run", "--json", path]）

1. 文件不存在→stderr 单行退 2（__main__ 层先验）；`load_plan_file` 异常（ValidationError/UnknownCommandError）→stderr 单行退 1。
2. **独立文档**：局部 `loaded = new_document(services)`（不动 self._doc/_archive_path；run 永远自带文档）。
3. `plan = Plan(steps=validated.steps)`→`plan.confirm(actor="cli-local")`→`loaded.bus.execute_batch(plan)`；BatchRollbackError e→stderr 单行含 `failed_ordinal`/`failed_command_id` 数值→退 1（空文档天然，无产出）。
4. 成功→写 metadata「存在即写入」：四必填 part_no/revision/material/source 必 set_metadata（覆盖默认，空串也写）；part_name/notes **仅当计划 dict 中存在该键时** set_metadata（空串也写）；缺省**绝不**写入（Document 保持无此键）。
5. outputs：step/stl 给→`services.formats.resolve(path).write(services.kernel, path)`（UnknownFormatError/EmptyGeometryError→1）；archive 给→`save_document(loaded.document, path)`；**全缺省→计划文件同目录 stem 三件** `<stem>.step/.stl/.mc.json`；部分给出→未给的不产出（archive 未给则**不产 .mc.json**）；目录不存在不创建（OSError→1）。
6. stdout 每件一行产出路径（产出顺序 step/stl/archive）；退 0。

### 3.3 validate 子命令（argv ["validate", path]）

- 文件不存在→2；扩展名非 {.json, .txt}→2 stderr 单行。
- `.json`：`load_plan_file`（独立上下文，不构造 Document/不执行）→stdout `valid: plan N step(s)`（N=len(steps)）退 0；异常→stderr 单行（含错误定位信息，如 `steps[2].params...` 尽量携带）退 1。
- `.txt`：逐行**只校验不执行**：#注释/空行跳过；内建命令行（new/open/save/export/meta/undo/redo/history/help/quit/exit/begin-batch/end-batch）做语法检查（如 meta 缺=→错误）但**不计入 N**；建模行 `parse_line`+`validate_params`——**N 只统计通过校验的建模命令行（含批内行）**；批结构三错误（未 begin 遇 end / 嵌套 begin / EOF 未闭合）→CliSyntaxError→**退 2**；建模参数/批内容校验失败→**退 1**；全过→stdout `valid: script N step(s)` 退 0。
- 判定原语与 execute_line 共用（§1 白名单允许的 helper 提取）；validate 不改任何文档状态（不构造 Document）。

### 3.4 history --json（execute_line 的 history 分支加 flag）

- `history --json`：stdout 一行 JSON：顶层恰 `commands` 键；每元素恰七键 `ordinal`(int)/`id`/`version`(int)/`params`(dict)/`timestamp_utc`/`confirmed_by`(str|null)/`amendments`（**仅非空时现**，元素含 at/actor/from_params/reason）；按 ordinal 升序；`json.dumps(..., ensure_ascii=False)`。
- 无文档/空历史→`{"commands": []}`。

### 3.5 测试（≥38 例总量）

- **test_run_json.py**（≥16 例）：文件不存在→2；JSON 语法损坏→1 单行；未知顶层键→1；缺 metadata→1；缺 steps→1；steps 空→1；未知 metadata 键→1；affected_object 不匹配→1；params 违规（radius 负）→1；显式非法 plan_id "plan-2026-09-17"→1；plan_id 缺省两次生成互不相等且匹配 ^[0-9a-f]{32}$（**单元级直调 plans：两次 validate_plan_dict 同 dict（删 plan_id）断言**）；成功全链（法兰三步计划：体积断言经读回 .mc.json→open_document→mass_properties==36794.3331588437 容差 1e-6+solid_count 1）；metadata 含 part_name/notes→存档两键值逐字相等；不含→存档 metadata 无这两键（断言键不存在，非空串）；空串值往返；outputs 全缺省→stem 三件+stdout 三行；outputs 只给 step→只产 step 一件；BatchRollbackError→1+stderr 含 failed_ordinal/failed_command_id 数值+无产出文件；run --json 两次调用独立（互不影响历史）。
- **test_validate.py**（≥12 例）：.json 合法 plan→0+`valid: plan 3 step(s)`；.json 各违规→1（复用 run_json 夹具）；.txt 合法脚本（3 建模+2 内建+注释）→`valid: script 3 step(s)`（内建行不计 N）；.txt 内建行语法错（meta 缺=）→1；未 begin 遇 end→2；EOF 未闭合→2；嵌套 begin→2；批内参数非法→1；未知建模 id→1；未知扩展 .x_t→2；文件不存在→2；validate 坏文件后进程再 validate 好文件→0（无状态残留——两次 main 调用）。
- **test_history.py**（≥10 例）：--json 顶层键集恰 {commands}；元素七键；confirmed_by null（new_document 后 Python API 执行无 confirmed_by——用 bus.execute(id,params) 不传）；confirmed_by "cli-local"（CLI 路径执行）；ordinal 升序；amendments 仅非空（edit_and_replay 制造一条）；空历史 `{"commands": []}`；**文本⇄JSON 等价闭环**：脚本执行 3 命令→history --json 解析→每条 `to_cli(id, params, registry)` 字符串→`parse_line(to_cli_line)`==(id, params)（params round-trip）；canonical 断言：cylinder 行 to_cli 显式含 `center=[0, 0, 0]`/`mode=new`（default 填充键在场——以 to_cli 实际输出为准断言键存在，禁凭印象写死格式）。
- 夹具：`build_app(discoverers=[])`；法兰计划 JSON 手写 dict→tmp_path 写盘（与 T11 examples/flange_plan.json 等价形态：metadata 四必填+steps 三条 affected_object 逐字 B.2）。

## 4. 通用纪律

SPDX 两行头（Apache-2.0）新文件全部；basedpyright strict 零 ignore；ruff 全过；测试 docstring 禁守卫字面量；禁 git。

## 5. 执行清单

- A0：sed 取计划 429-463+660-740；cat src/mycad/cli/session.py+__main__.py（T10a 实况）；cat tests/cli/test_batch.py | head -40（helper 形态）。
- A1：写 plans.py（两块：ValidatedPlan/Outputs+validate_plan_dict；load_plan_file）。
- A2：__main__.py 加 run --json/validate 分发；session.py 提取共享 helper（若需）+追加 run_json。
- A3：session.py 追加 validate_file+history --json 分支。
- A4：写 test_run_json.py（两块）；跑绿。
- A5：写 test_validate.py；跑绿。
- A6：写 test_history.py；跑绿。
- A7：scoped 四门：`.venv/bin/python -m pytest tests/cli/ -q`（全目录，T10a 既有测试必须仍绿）+ `.venv/bin/basedpyright src/mycad/cli/ tests/cli/` + `.venv/bin/ruff check src/mycad/cli/ tests/cli/` + `format --check` 同路径。
- A8：evidence §T10b（交付物/四门计数/设计决策：metadata 存在即写入语义/outputs 部分给出语义/validate 与执行共享 helper 提取/N 计数口径）。
- A9：DoneClaim JSON（{"task":"T10b","status":"DONE","deliverables":[...],"gates":{...},"deviations":[...],"notes":"..."}）。
