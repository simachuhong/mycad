# T7a：builtin_commands 包（defs.py + 8 CommandSpec + 附录 A 转录测试）

你是 MyCAD phase-0 计划的 T7a 执行者。本提示词是唯一任务书，逐字执行。
计划文件 `.omo/plans/phase0-mvp.md` 行 350-379（T7 段）+ 附录 A（550-662 行）为权威规格。
**第一动作：`cat` 本文件已完成；随后 A0 逐项读取参考源码，禁止跳过。**

## 反停摆五纪律（每回合必须遵守）
1. 禁写清单文件/计划文件；执行清单只在脑内。
2. 单次写文件 ≤100 行（大文件用 `cat >` 首批 + `cat >>` 追加分批）。
3. 每回合只做一个小动作（写一个文件/跑一个命令/读一个文件）。
4. 禁长推理：写码前已把设计钉死在本文，照抄执行即可；遇规格冲突记 deviation 后选本文规则。
5. BLOCKED（环境坏/依赖缺）立即停并输出 BLOCKED 原因，勿反复重试。

## 白名单（仅允许创建/修改以下文件）
- `src/mycad/builtin_commands/__init__.py`（新建）
- `src/mycad/builtin_commands/defs.py`（新建）
- `src/mycad/builtin_commands/specs.py`（新建）
- `tests/builtin_commands/__init__.py`（新建，空文件）
- `tests/builtin_commands/test_defs.py`（新建）
- `tests/builtin_commands/test_specs.py`（新建）
- `.omo/evidence/task-7-phase0-mvp.md`（新建，只写 §T7a 段）

**禁改**：src 与 tests 下其余一切文件（含 commands/demo.py、plugins/、agent/、app.py——那是 T7b/T7c）；禁 git 操作。

## 通用规则
- 每个新建 .py 文件头两行 SPDX：`# SPDX-License-Identifier: MIT` + `# SPDX-FileCopyrightText: 2026 MyCAD Contributors`（参照 src/mycad/core/exceptions.py 现有文件头格式）。
- basedpyright strict 零 ignore 零 type:ignore；ruff（E/F/W/I/B/UP/C4）零豁免。
- TDD：先写测试（红）→ 实现（绿）也可先实现后测试，但四门必须全绿才算完。
- 所有 Python 代码 3.12+ 语法。

## A0 前置读（必须依次 cat/读，禁止跳过）
1. `sed -n '550,662p' .omo/plans/phase0-mvp.md`（附录 A 全文——defs.py 与 specs.py 的逐字来源）。
2. `cat src/mycad/commands/validation.py`（T3 校验器）。**关键勘察**：确认校验器对 schema 内未知关键字（`description`/`const`/`default`）的处理——
   - 若未知关键字被拒绝/报错：defs.py 转录时**剥离 `description` 键**（纯文档用途），`const` 改写为等值单元素 `enum`（`{"const":"plane"}`→`{"enum":["plane"]}`），`default` 若不支持则同样处置；每处记 deviation。
   - 若被忽略：`description` 与 `const` 逐字保留。
   - 以 validation.py 实际代码为准，evidence 记录勘察结论。
3. `cat src/mycad/commands/spec.py`（CommandSpec/CliSyntax 签名）。
4. `cat src/mycad/commands/registry.py`（CommandRegistry(schema_defs=...) 构造与 register/get）。
5. `cat src/mycad/core/document.py` 的 AFFECTED_OBJECTS 段与 AffectedObject Literal（head -60 即可）。
6. `cat tests/commands/test_registry.py` 或任一现有测试文件（测试风格参照：SPDX 头/导入风格/断言风格）。

## 钉死设计（照抄，勿发明）

### defs.py（单一常量表，附录 A.0 逐字转录）
`COMMAND_SCHEMA_DEFS: Mapping[str, Any]`（模块级常量，dict 字面量）——键恰 11 个：
`FaceSelector, EdgeSelector, Position, Depth, Pattern, Profile, Mode, Center3, Positive, Tool, Hole`。
每个 def 的内容逐字转录附录 A.0 JSON（经 A0 勘察决定 description/const/default 的处置）：
- FaceSelector=oneOf 两分支（plane：required[surface,axis]，properties surface const plane、axis enum 六带符号轴、rank integer minimum 0、additionalProperties false；cylinder：required[surface]，surface const cylinder、axis enum 六轴+空串、rank 同、additionalProperties false）。
- EdgeSelector=object required[parent_faces]，parent_faces array items $ref FaceSelector minItems 1，curve enum[line,circle,""]，additionalProperties false。
- Position=oneOf 单分支（kind const center，required[kind]，additionalProperties false）。
- Depth=oneOf 两分支（through_all：kind const；blind：kind const + value number exclusiveMinimum 0.0，required[kind,value]）。
- Pattern=oneOf 单分支（polar：kind const polar、radius exclusiveMinimum 0.0、count integer minimum 2 maximum 64、start_angle_deg number default 0.0，required[kind,radius,count]，additionalProperties false）。
- Profile=oneOf 两分支（circle：type const circle、radius Positive、center 2 元数组 default [0.0,0.0]，required[type,radius]；rect：type const rect、width/height Positive、center 同，required[type,width,height]）。
- Mode=string enum[new,add,cut] default "new"。
- Center3=array items number minItems 3 maxItems 3 default [0.0,0.0,0.0]。
- Positive=number exclusiveMinimum 0.0。
- Tool=oneOf 两分支（box：size_x/size_y/size_z $ref Positive、center $ref Center3，required[type,size_x,size_y,size_z]；cylinder：radius/height $ref Positive、center $ref Center3，required[type,radius,height]）。
- Hole=object required[target_face,position,diameter,depth]，properties 四键均 $ref（FaceSelector/Position/Positive/Depth），additionalProperties false。
**内部共享一律 `{"$ref": "#/$defs/<Name>"}`，禁止复制子结构。**

### specs.py（8 条 CommandSpec）
`from mycad.commands.spec import CliSyntax, CommandSpec`；每条 `CommandSpec(id=..., version=1, summary_en=..., label_zh=..., params_schema=..., cli=CliSyntax(verb_aliases=(...,)), undo_compensation="history_replay")`。
模块级 `BUILTIN_COMMAND_SPECS: tuple[CommandSpec, ...]`（A.1 顺序）。8 条逐字：

1. `feature.box`，cli=("box",)，summary_en="Create a rectangular box"，label_zh="长方体"；schema={"type":"object","properties":{"size_x":{"$ref":"#/$defs/Positive"},"size_y":{"$ref":"#/$defs/Positive"},"size_z":{"$ref":"#/$defs/Positive"},"center":{"$ref":"#/$defs/Center3"},"mode":{"$ref":"#/$defs/Mode"}},"required":["size_x","size_y","size_z"],"additionalProperties":false}。
2. `feature.cylinder`，cli=("cylinder",)，"Create a cylinder"/"圆柱体"；schema=properties{radius:Positive, height:Positive, center:Center3, mode:Mode}, required[radius,height]。
3. `feature.extrude`，cli=("extrude",)，"Extrude a parametric profile"/"拉伸"；schema=properties{profile:{$ref Profile}, distance:{"type":"number"}, mode:Mode}, required[profile,distance]。
4. `feature.revolve`，cli=("revolve",)，"Revolve a parametric profile"/"旋转"；schema=properties{profile:{$ref Profile}, axis:oneOf[{"enum":["X"]},{"enum":["Y"]},{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}]（const 处置同 A0 结论）, angle_deg:{"type":"number","exclusiveMinimum":0.0,"maximum":360.0,"default":360.0}, mode:Mode}, required[profile,axis]。
5. `feature.hole`，cli=("hole",)，"Drill a predicate-located hole"/"孔"；**params_schema={"$ref":"#/$defs/Hole"}（根级 $ref，无 type/object 包装）**。
6. `feature.hole_pattern`，cli=("hole-pattern",)，"Pattern a predicate-located hole"/"孔阵列"；schema=properties{base_hole:{$ref Hole}, pattern:{$ref Pattern}}, required[base_hole,pattern], additionalProperties false。
7. `modify.fillet`，cli=("fillet",)，"Fillet selected edges"/"圆角"；schema=properties{edges:{"type":"array","items":{"$ref":"#/$defs/EdgeSelector"},"minItems":1}, radius:{$ref Positive}}, required[edges,radius]。
8. `modify.boolean_cut`，cli=("cut",)，"Subtract an inline tool solid"/"差集"；schema=properties{tool:{$ref Tool}}, required[tool], additionalProperties false（**不接受 mode 键**）。

### __init__.py
再导出：`COMMAND_SCHEMA_DEFS`、`BUILTIN_COMMAND_SPECS`、`BUILTIN_COMMAND_IDS`（tuple(spec.id for spec in BUILTIN_COMMAND_SPECS)）。

### test_defs.py（附录 A.0 双重独立转录比对）
- 断言 COMMAND_SCHEMA_DEFS 键集合恰为 11 名（sorted 比较）。
- **期望值手写独立转录附录 A.0（禁从 defs.py import 后反录对比）**：对 11 个 def 中至少 FaceSelector（两分支全字段）、Depth、Pattern、Profile、Tool、Hole 做逐字段相等断言（expected 为测试文件内字面量 dict）；其余 def（EdgeSelector/Position/Mode/Center3/Positive）做关键字段断言（required/enum/min/max/default）。
- $ref 引用形态断言：Hole 的 properties 四值均恰为 {"$ref":"#/$defs/<Name>"}；Tool 两分支的 Positive/Center3 均为 $ref。
- 禁复制子结构守卫：defs.py 文本中 `"exclusiveMinimum": 0.0` 出现次数 == 2（Positive 与 Depth.blind.value 各一处，其余全经 $ref）——若附录转录致计数不同，按实际调整断言并记 deviation。

### test_specs.py（8 spec 逐字段 + 注册表 + 守卫）
- 8 条 spec 逐字段断言：id/version=1/summary_en/label_zh（逐字串）/cli.verb_aliases/undo_compensation=="history_replay"/params_schema 与期望字面量 dict 相等（期望手写）。feature.hole 断言 params_schema == {"$ref":"#/$defs/Hole"}。
- 自建注册表：`registry = CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)`，逐个 register(BUILTIN_COMMAND_SPECS)，断言 `sorted(s.id for s in registry)`（或等价 API）== 附录 A.1 8 id 排序列表。
- **validate_params 冒烟（注入本表）**：`from mycad.commands.validation import validate_params`；①box 合法 {size_x:10,size_y:20,size_z:30} → 返回 default 填充 dict（center==[0,0,0]、mode=="new"）；②box size_x=-1 → pytest.raises(ValidationError)；③hole 经根级 $ref：合法 {target_face:{surface:"plane",axis:"+Z",rank:0},position:{kind:"center"},diameter:20.0,depth:{kind:"through_all"}} → 通过；④hole_pattern base_hole 同形态+diameter 6.0+pattern polar → 通过；⑤pattern kind="linear" → ValidationError。
- P1/P2 泄漏守卫：注册表 id 集不含 chamfer/shell/union/intersect/pattern_linear/mirror/draft/sweep/datum.*（参数化断言 each not in ids）。
- AFFECTED_OBJECTS 静态断言（从 mycad.core.document import AFFECTED_OBJECTS）：恰 8 键且键集合==注册表 id 集合；len(set(values))==8；set(values())=={"box_body","cylinder_body","extruded_body","revolved_body","hole","hole_pattern","edge","tool_body"}。
- PlannedCommand 表外失败：`from mycad.core.document import PlannedCommand`；参数化 ["feature.sweep","modify.chamfer","datum.xy","", "feature.boxx"] 构造 → pytest.raises(ValidationError)（或规格实际异常类型，先 cat document.py 确认 PlannedCommand 门行为）。
- **AST 单一赋值守卫**：walk `src/mycad/**/*.py`（pathlib rglob "*.py"），ast.parse 每文件，找 `Assign` 且 target id=="COMMAND_SCHEMA_DEFS"，断言命中文件列表恰为 ["src/mycad/builtin_commands/defs.py"]（路径相对比较或 endswith）。
- CLI 别名唯一性：cut 仅出现在 modify.boolean_cut 的 verb_aliases；8 个别名两两不同。

### evidence §T7a（.omo/evidence/task-7-phase0-mvp.md 新建）
标题 `# Task 7 — phase-0 evidence`，`## §T7a builtin_commands 包`：交付物清单、四门结果、A0 勘察结论（description/const/default 处置）、deviations 列表（D 编号接续无要求，本段内从 D1 起）。

## 执行清单（按序，每步一回合）
- A0：六项前置读（上文）；把 const/default 勘察结论写进脑内。
- A1：写 tests/builtin_commands/__init__.py（空）+ test_defs.py 首批（≤100 行）。
- A2：test_defs.py 追加至完整。
- A3：跑 pytest tests/builtin_commands/test_defs.py → 红（defs.py 缺）。
- A4：写 src/mycad/builtin_commands/__init__.py 占位（先空再导出亦可）。
- A5：写 defs.py 首批（≤100 行，A.0 前半）。
- A6：defs.py 追加后半至 11 def 全。
- A7：跑 test_defs.py → 绿；不绿修 defs.py（禁改测试期望，除非期望本身抄错附录——此时记 deviation）。
- A8：写 test_specs.py 首批。
- A9：test_specs.py 追加至完整。
- A10：跑 test_specs.py → 红（specs.py 缺）。
- A11：写 specs.py（≤100 行/批，两批内）。
- A12：写 __init__.py 导出；跑全 tests/builtin_commands/ → 绿。
- A13：scoped 四门（下节）全绿。
- A14：写 evidence §T7a；输出 DoneClaim。

## scoped 四门（A13，全部用 .venv/bin/python）
1. `.venv/bin/python -m pytest tests/builtin_commands/ -q` → 全 passed。
2. `.venv/bin/python -m basedpyright src/mycad/builtin_commands/ tests/builtin_commands/` → 0 errors 0 warnings 0 notes。
3. `.venv/bin/python -m ruff check src/mycad/builtin_commands/ tests/builtin_commands/` → 全过。
4. `.venv/bin/python -m ruff format --check src/mycad/builtin_commands/ tests/builtin_commands/` → 全过（或 format 后复跑 check）。

## DoneClaim（最后一条消息，仅 JSON 代码块）
```json
{"claim":"DoneClaim","slice":"T7a","deliverables":["src/mycad/builtin_commands/__init__.py","src/mycad/builtin_commands/defs.py","src/mycad/builtin_commands/specs.py","tests/builtin_commands/__init__.py","tests/builtin_commands/test_defs.py","tests/builtin_commands/test_specs.py",".omo/evidence/task-7-phase0-mvp.md §T7a"],"four_gates":{"pytest":"<N passed>","basedpyright":"0 errors 0 warnings 0 notes","ruff_check":"All checks passed","ruff_format":"<结果>"},"a0_findings":"<description/const/default 勘察结论一句话>","deviations":["<每条一句>"],"notes":"<其他>"}
```
