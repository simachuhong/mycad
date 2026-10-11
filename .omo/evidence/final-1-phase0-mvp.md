# F1 — Plan compliance audit（阶段 0 MVP 最终验证波）

**结论：REJECT**

审计范围 = 计划 `.omo/plans/phase0-mvp.md:506-508` 的 F1 条目五项。审计人：F1 只读
审查代理。审计时点：2026-10-11，HEAD = `feecf03`（22 commits，T1–T11 全部标记完成）。
审计方式：只读命令（rg / cat / git show / git diff / pytest --collect-only / python3
纯计算）。本文件是本次审计写出的唯一文件，未修改仓库任何其他内容。

REJECT 的唯一硬性理由见 **问题 P1**：计划明文钉死、并被 AGENTS.md 当作执行器引用的
「零类型抑制」不变量守卫 `tests/test_layering.py::test_no_type_ignore_or_pyright_ignore_sites`
在 HEAD 上是**空转测试**（实测扫描 0 个文件），且仓库中**确实存在 3 处违规的
`# type: ignore`**（`tests/core/` 下，不在 `tests/typing/` 白名单内）。这是「守卫存在
但失效 + 被守卫的不变量实际被破坏」，属 MISSING，不是风格偏好。

其余四项（Must have 覆盖、8 条命令 id 逐字比对、ADR-001..006 一致性、A1–A20 / R1–R18
处置）**全部通过**，无静默缺失。T11 的 D8–D15 与 §T11-pre 偏差记录经逐条核验属实。

---

## 1. Must have C1–C10 覆盖矩阵

| # | 需求/决策 | 落点文件 / 测试 | 实际证据 | 判定 |
|---|---|---|---|---|
| C1 | 环境与工程骨架（src 布局 / Python 门 / build123d 精确 pin / OCP patch range / uv.lock / ruff+basedpyright strict+pytest / CI 恰好三 job / 镜像+离线安装文档） | `pyproject.toml`、`pyrightconfig.json`、`uv.lock`、`.github/workflows/ci.yml`、`README.md`、`tests/test_ci_workflow.py` | `pyproject.toml:8` `requires-python=">=3.12,<3.15"`；`:16` `build123d==0.11.1`；`:17` `cadquery-ocp-novtk>=7.9.3.1.1,<7.9.4` 且 `:13-14` 写明 7.9.4 排除理由；`pyrightconfig.json` 四键逐字=计划 #round8-1；`ci.yml:14` matrix 恰好 `[ubuntu-22.04, ubuntu-24.04, windows-latest]` + 四质量门；`README.md:101-122` 国内镜像（清华/阿里）+ conda/wheelhouse 离线附录 | **PARTIAL**（见 P2/P3：ruff select 集与 pytest addopts 偏离 T1 原文且**无任何证据文件记录**） |
| C2 | geom 适配层（8 条 P0 原语 / 几何谓词选择器 / 质量属性 / 可调弦差 tessellation / STEP·STL I/O / 后端类型不越界） | `src/mycad/geom/kernel.py`、`_b123_ops.py`、`_b123_features.py`、`selectors.py`、`io.py`、`tests/test_layering.py`、`tests/geom/*` | `kernel.py:106 mass_properties`、`:111 tessellate(linear_tolerance_mm, angular_tolerance_deg)`、`:121 export_step`、`:126 export_stl`、`:131-149 face_candidates/resolve_face/resolve_edges`；`_b123_ops.py:120 _parse_box` `:131 _parse_cylinder`；`_b123_features.py:134 _extrude` `:204 _revolve` `:227 _fillet` `:297 _boolean_cut` `:464 _hole` `:511 _hole_pattern` → 8 条齐；封层由 `tests/test_layering.py::test_src_has_no_backend_imports`（`rglob("*.py")`，有效）+ `tests/test_scope_audit.py::test_backend_imports_are_confined_to_geom` 双守 | **COVERED** |
| C3 | 命令模型与注册表（CommandSpec：稳定 id+version+Schema+校验+CLI 文案；注册表驱动三入口同源；8 条 id 与 UI 初稿逐字一致） | `src/mycad/commands/spec.py`、`registry.py`、`validation.py`、`grammar.py`、`src/mycad/builtin_commands/specs.py`、`tests/builtin_commands/test_specs.py` | `specs.py:25-180` 八条 `CommandSpec(id/version/summary_en/label_zh/params_schema/cli/undo_compensation)`；`test_specs.py:32-43 EXPECTED_IDS` 字面量 + `:261-262` 断言 `BUILTIN_COMMAND_IDS == EXPECTED_IDS`；逐字比对结果见下文 §2 | **COVERED** |
| C4 | Document + Command Bus（唯一真相源 / metadata / NamedGroup / headless 信号 / undo·redo=删命令+全量重放 / 重放失效显式报错 / 批事务快照回滚 / Plan 六态机 / 存档 v1+迁移钩子） | `src/mycad/core/document.py`、`bus.py`、`groups.py`、`signals.py`、`plan.py`、`persistence.py`、`schema_v1.py`、`migrations/`、`tests/core/*` | `bus.py:127-149 undo/redo`、`:151-165 _rebuild`（`kernel.reset()` + 全历史 `record=False` 重放，`:158-164` 对 `GeometryBuildError`/`TopologyReferenceError` 补 `ordinal=cmd.ordinal` 后再抛）；`:196-235 execute_batch`（`copy.deepcopy` 快照 → 失败 `_restore_commands/_restore_metadata` → `BatchRollbackError(failed_ordinal, failed_command_id, reason, executed_ids)`）；`:167-194 edit_and_replay`；`document.py:102 METADATA_KEYS`；`groups.py:18 NamedGroup`；`signals.py:21-28` 五信号；`plan.py:19` 六态 + `:25-30` 恰好 6 条边；`schema_v1.py:22-23` `format/version` + `core/migrations/` 钩子 | **COVERED** |
| C5 | CLI（console script `mycad` / ASCII REPL + 脚本 / 文本⇄JSON 等价 / 全套子命令 / 退出码 0·1·2 / 法兰端到端） | `pyproject.toml:37`、`src/mycad/cli/__main__.py`、`session.py`、`plans.py`、`tests/cli/*` | `pyproject.toml:37 mycad = "mycad.cli.__main__:main"`；`__main__.py:5-8` 退出码契约 0/1/2 明文，`:51-90` 派发 repl/run/run --json/validate/commands/plugins/help；`session.py:84-94` + `:572-582` 内置分发表 new/open/save/export/meta/undo/redo/history/help/quit/exit。**注：AGENTS.md「validate/commands/plugins 尚未实现，退出码 2」的描述已过时**（T10b/c 于 `014bcd5`/`58493b6` 落地），属文档滞后，不是实现缺口 | **COVERED** |
| C6 | 质量与验收（法兰 golden 全精度 + `_formula` / STEP 往返 / 双 examples / Apache-2.0 NOTICE 归属 / SPDX 头） | `tests/golden/flange_golden.json`、`tests/test_acceptance_flange.py`、`tests/formats/test_export_roundtrip.py`、`examples/`、`NOTICE`、`LICENSE`、`tests/test_notice.py`、`tests/test_spdx.py` | golden A `36794.3331588437` + `_formula "math.pi*8*(40**2-10**2-4*3**2)"`，B `68455.3039217216` + `_formula`，两组均带 bbox/solid_count/cylindrical_faces；`test_acceptance_flange.py:147/177/185/230/261/292/301` 覆盖 edit_and_replay / Group B 闭式自洽 / Plan confirm+STEP 往返 / 批撤销 / 脚本⇄计划同几何 / LICENSE+NOTICE / 中文路径；`NOTICE` 115 行，运行时闭包逐名归属 | **COVERED** |
| C7 | 扩展缝（entry points `mycad.commands`/`mycad.formats` / 模块 `manifest` 属性三形态 / API 主版本门控 / pre·post 与保存信号 / 插件=全信任） | `src/mycad/plugins/discovery.py`、`manifest.py`、`types.py`、`manager.py`、`loader.py`、`plugins_examples/`、`tests/plugins/*` | `discovery.py:30-31` 两组常量 + `:146` 默认组元组 + `:160 importlib.metadata.entry_points(group=...)`；`manifest.py:45-141 resolve_manifest` 三形态（dict / `PluginManifest` 实例 / 零参 callable）；`types.py:24-25 CURRENT_API_VERSION="1.0"` / `CURRENT_API_MAJOR=1`；`signals.py:21-28` 五信号 | **COVERED** |
| C8 | FormatProvider 缝（name×vendor×priority / can_read·can_write / target=shape / STEP 只写 + STL 只写 / priority 默认 100 取小值、相同报错 / 导入三级枚举仅定义） | `src/mycad/formats/base.py`、`registry.py`、`providers/step_provider.py`、`stl_provider.py`、`tests/formats/*` | `base.py:40-44 priority/can_read/can_write/target: Literal["shape","xcaf"]`；`registry.py:34-45` 同 priority 且扩展名重叠抛 `ProviderConflictError`，`:58 min(candidates, key=priority)`；两个 provider 均 `priority=100, can_read=False, can_write=True, target="shape"`；STEP 读 API 仅 `tests/helpers/step_roundtrip.py`，由 `tests/formats/test_guards.py` + `test_scope_audit.py:79-80` 白名单守 | **COVERED** |
| C9 | 跨平台纪律（纯可移植代码 / 三平台 CI 第一天就绪 / ADR-006 锁 T1·T2·T3 与 glibc≥2.31） | `.github/workflows/ci.yml`、`tests/test_ci_workflow.py`、`tests/test_scope_audit.py:199`、`docs/adr/ADR-006-platform-tiering.md` | `ci.yml:14` 三 job；`test_scope_audit.py:199 test_src_uses_pathlib_not_hardcoded_separators`；`ADR-006:11-16` T1/T2/T3 + glibc≥2.31 基线 + 海光·兆芯归 T1/T2 + 申威不纳入。**已知遗留（非缺陷）**：无 GitHub 远端，三 job 从未真实执行，T1 证据 §4 与 T11 D15 均已如实标注「就绪未实测」并禁止下游虚报 | **COVERED（附已记录遗留）** |
| C10 | 6 份 ADR（001 命令总线与重放 / 002 JSON 存档 / 003 扩展点与插件 API 版本 / 004 MCP 边界 / 005 格式提供方分级 / 006 平台分层） | `docs/adr/ADR-001..006-*.md`、`tests/test_adr_docs.py` | 六文件齐备（42/32/33/32/29/39 行）；`test_adr_docs.py:104` 断言恰好六个编号文件、`:117` 五段式表头、`:125` 逐 ADR 必含/必禁词、`:134` `## 基线偏离` 恰好两处且按文件名定位（ADR-001 / ADR-006）、`:146` 禁早产实现措辞 | **COVERED** |

**统计：COVERED 9 / PARTIAL 1 / MISSING 0。**

---

## 2. 8 条命令 id 逐字比对（`docs/UI设计初稿.md` vs `src/mycad/builtin_commands/specs.py`）

比对方法：取 UI 初稿第 150–205 行命令目录中全部标注 **P0** 的条目，与 `specs.py` 的
`CommandSpec.id` 字面量逐字符比对（含点号、下划线、大小写）。

| UI 初稿行号 | UI 初稿 id | UI 初稿显示名 | specs.py 行号 | specs.py id | specs.py `label_zh` | 逐字一致 |
|---|---|---|---|---|---|---|
| `docs/UI设计初稿.md:170` | `feature.box` | 长方体 | `specs.py:27` | `feature.box` | 长方体 | ✅ |
| `docs/UI设计初稿.md:169` | `feature.cylinder` | 圆柱体 | `specs.py:47` | `feature.cylinder` | 圆柱体 | ✅ |
| `docs/UI设计初稿.md:164` | `feature.extrude` | 拉伸 | `specs.py:66` | `feature.extrude` | 拉伸 | ✅ |
| `docs/UI设计初稿.md:165` | `feature.revolve` | 旋转 | `specs.py:84` | `feature.revolve` | 旋转 | ✅ |
| `docs/UI设计初稿.md:167` | `feature.hole` | 孔 | `specs.py:119` | `feature.hole` | 孔 | ✅ |
| `docs/UI设计初稿.md:168` | `feature.hole_pattern` | 孔阵列 | `specs.py:129` | `feature.hole_pattern` | 孔阵列 | ✅ |
| `docs/UI设计初稿.md:176` | `modify.fillet` | 圆角 | `specs.py:146` | `modify.fillet` | 圆角 | ✅ |
| `docs/UI设计初稿.md:180` | `modify.boolean_cut` | 差集 | `specs.py:167` | `modify.boolean_cut` | 差集 | ✅ |

**结论：8/8 逐字一致，零差异。** `label_zh` 亦与 UI 初稿「显示名」列逐字一致（计划未
强制要求，属正向冗余）。

反向核对（命名空间保留，ADR-003 §9）：UI 初稿列出但阶段 0 **未注册**的 id 共 20 条
（`sketch.*` 5、`feature.sweep`、`modify.chamfer/shell/boolean_union/boolean_intersect/
pattern_linear/pattern_circular/draft/mirror`、`datum.*` 3、`inspect.measure`、`view.*` 4、
`agent.*` 2）。`tests/builtin_commands/test_specs.py:389` 以 `feature.sweep`/`modify.chamfer`/
`datum.xy` 为负例断言未注册；`tests/test_scope_audit.py::test_no_out_of_scope_code` 断言
无 `view.`/`sketch.`/`datum.` 命令 id 注册。符合计划。

> 备注（非缺陷）：计划 F1 条目写「`docs/UI设计初稿.md:160-185`」，实际 8 条 P0 id 落在
> 164–180 行，全部落在该区间内；区间上下界只是粗略引用，不构成不符。

---

## 3. ADR-001..006 存在性与一致性

六份 ADR 齐备，文件名契约（`ADR-00N-<lowercase-ascii-slug>.md`）与五段式结构
（Context / Decision / 基线偏离(仅 001·006) / Consequences / References）由
`tests/test_adr_docs.py` 机器化锁定。以下为计划点名的四处重点抽查。

### 3.1 ADR-001「唯一写入路径 + undo=全量重放」vs `src/mycad/core/bus.py`

| ADR-001 决策条 | 代码证据 | 一致 |
|---|---|---|
| §1 唯一写入路径：单命令 / undo·redo / 批事务 / 历史参数编辑重放只能经 Bus | `bus.py:79-119 _execute_one` 是唯一管线（注释 #round11-2 明示 execute / execute_batch / open-replay 全部汇入）；`Document` 的四个写入内部方法 `_append_command/_pop_commands/_restore_commands/_restore_metadata` 以下划线私有，由 Bus 在 `__init__:53-69` 一次性绑定 | ✅ |
| §2 undo = 删命令 + 全量重放；redo 对称；不做 per-command inverse、不做 brep 快照 | `bus.py:127-136 undo`（`_pop_commands(n)` → 压 redo 栈 → `_rebuild()`）；`:138-149 redo`（重挂 → `_rebuild()`）；`:151-165 _rebuild`（`kernel.reset()` + 全历史重放）。仓库无 inverse/补偿代码，无 brep 快照缓存 | ✅ |
| §3 批事务 = 执行前快照、整体回滚、all-or-nothing | `bus.py:206-207` 执行前 `copy.deepcopy(commands)` + `metadata_snapshot()`；`:213-233` 任一异常即 restore + `_rebuild` + `plan.mark_failed()` + 抛 `BatchRollbackError`；无「返回错误对象继续执行」分支 | ✅ |
| §4 重放引用失效必须显式报错并指向命令 | `bus.py:161-164` 捕获 `TopologyReferenceError`，`ordinal is None` 时以当前命令 `ordinal` 重抛（`GeometryBuildError` 同理，`:157-160`）；异常签名由 `tests/test_exceptions.py` 锁 `ordinal` 字段 | ✅ |
| §6 `undo_compensation` 字段存在且阶段 0 唯一取值 `"history_replay"` | `specs.py` 八条 spec 全部 `undo_compensation="history_replay"`（`:44, :63, :81, :116, :126, :143, :164, :178`） | ✅ |
| 基线偏离 ②（headless 投影：Chat 确认→`confirmed_by`；预览后置） | `bus.py:72-73 execute(..., confirmed_by)`；`:111 confirmed_by=confirmed_by` 入史；`kernel.py:111 tessellate` 只交付数据接口，无 UI 代码 | ✅ |

另：ADR-001 §5 坐标与单位约定（mm / mm³ / `_deg` 后缀 / 极阵列 `start_angle_deg=0` 对齐
全局 +X）与 `specs.py` 的 `angle_deg`、`pattern.start_angle_deg` 键名一致。

### 3.2 ADR-002 审计六字段 vs `src/mycad/core/schema_v1.py`

| ADR-002 决策条 | 代码证据 | 一致 |
|---|---|---|
| §1 UTF-8 JSON，扩展名 `.mc.json` | `src/mycad/cli/session.py:107` 对 `open`/`save` 强制 `.mc.json` 后缀 | ✅ |
| §2 顶层 schema `format/version/metadata/commands/named_groups` | `schema_v1.py:25 _TOP_LEVEL_KEYS = ("format","version","metadata","commands","named_groups")`，`:116 _reject_unknown(root, _TOP_LEVEL_KEYS, ...)` 闭合 | ✅ |
| §2 `format="mycad.document"`, `version=1` | `schema_v1.py:22-23 ARCHIVE_FORMAT/ARCHIVE_VERSION` | ✅ |
| §3 named_groups 元素恰好三键 name/faces/edges | `schema_v1.py:93-105 _validate_group`（必含三键 + `_reject_unknown` 闭合） | ✅ |
| **§4 审计六字段 id/version/params/ordinal/timestamp_utc/confirmed_by** | **`schema_v1.py:27 _COMMAND_KEYS = ("id","version","params","ordinal","timestamp_utc","confirmed_by")`**；`:52-54` 六字段缺一即 `ValidationError`；`:62 ordinal` int≥0；`:64 timestamp_utc` str；`:66 confirmed_by` str\|null | ✅ **逐字一致** |
| §5 可选 `amendments` 四键 at/actor/from_params/reason | `schema_v1.py:28 _AMENDMENT_KEYS` + `:69-90` 校验 | ✅ |
| §6 重放/编辑不改写原 timestamp | T11 实测（`task-11` §T11 实测数据）：Group B 经 edit_and_replay 后「三条命令 ordinal/timestamp_utc 均不变、各追加 1 条 amendment」 | ✅ |
| §7 迁移钩子先行、v1 空表 | `src/mycad/core/migrations/__init__.py` 存在；`task-6` 证据记录 migrations 链 4 例测试 | ✅ |
| §8 无任何导入型历史节点 | `tests/test_scope_audit.py:70-74 OUT_OF_SCOPE_IDENTIFIERS`（`document.import_step` / `imported_solid` / `ImportSourceMissingError`）断言不存在 | ✅ |

`document.py:102 METADATA_KEYS` 与 `schema_v1.py:26 _METADATA_KEYS` 同为
`part_no/revision/material/source/part_name/notes`，与 C4/A15 的 PLM 缝要求一致。

### 3.3 ADR-003 api_version 主版本门控 vs `src/mycad/plugins/manifest.py`

| ADR-003 决策条 | 代码证据 | 一致 |
|---|---|---|
| §2 `CURRENT_API_VERSION="1.0"`，主版本为 1 兼容、其他主版本一律跳过 | `types.py:24-25 CURRENT_API_VERSION="1.0"` / `CURRENT_API_MAJOR=1`；`manifest.py:80-85 _gate`：`int(api_version.split(".",1)[0]) != CURRENT_API_MAJOR` → `incompatible-api`；dict 路径同规则 `:101-106`。`tests/plugins/test_types.py:92-93` 锁常量；`tests/fixtures/plugins/mycad_plugin_matrix/` 提供 1.0 / 1.5 / 2.0 / v1 / abc 五个矩阵夹具 | ✅（1.5 兼容、2.0 跳过，即「主版本门控」而非精确比对） |
| §2 manifest 五字段 id/version/api_version/permissions/homepage | `manifest.py:41-42 _REQUIRED_KEYS={id,version,api_version}`、`_KNOWN_KEYS` 并上 `{permissions,homepage}`，超集即 `damaged-manifest` | ✅ |
| §3 定位算法：模块属性固定名 `manifest`，接受 callable/dict/dataclass 三形态；缺失=missing、损坏=manifest-error、主版本不符=incompatible-api | `manifest.py:53-70 resolve_manifest`；三类 reason code 由 `get_args(WARNING_REASON)[0..2]` 派生（`:36-38`），不硬写字面量 | ✅ |
| §3 「api_version 先于其他字段判定」 | `manifest.py:90-106`：键集检查 → api 门控 → 其余字段；顺序与 ADR 文字一致 | ✅ |
| §1 两个 entry 组先落地，`mycad.datum`/`mycad.inspect` 仅文字预留 | `discovery.py:30-31` 只有两个组常量，`:146` 默认组元组同两项；src 无 datum/inspect 组字面量 | ✅ |
| §6 信任模型：permissions 仅声明、不沙箱 | `manifest.py:131-140 _permissions_from` 只做类型规范化，无执行期强制；ADR-003 §6 与 README/计划 T9 一致 | ✅ |
| §9 命名空间保留 | 见 §2 反向核对 | ✅ |

### 3.4 ADR-005 商业格式墙是否被遵守

| 约束 | 证据 | 结论 |
|---|---|---|
| 不引入 JT / Parasolid(x_t) / ACIS(sat) / sldprt / NX / CATIA 适配代码 | `tests/test_scope_audit.py:64-66 COMMERCIAL_FORMATS = {jt, parasolid, acis, sat, x_t, sldprt, nx, catia}`，`:160` 在 `test_no_out_of_scope_code` 中逐项断言；匹配规则=「点号后缀 + 文件名 stem」（D10 记录的可执行化改写） | ✅ 遵守 |
| 不碰 DWG / 逆向库 | 运行时闭包仅 46 包（NOTICE 逐名），无 ODA/CAD Exchanger/DWG 相关分发 | ✅ 遵守 |
| 阶段 0 产品化范围 = STEP 只写 + STL 只写；STEP 读仅 `tests/helpers/` | `step_provider.py:24-25 can_read=False, can_write=True`；`stl_provider.py` 同；`test_scope_audit.py:76-80 STEP_READ_WHITELIST="tests/helpers/step_roundtrip.py"` + `tests/formats/test_guards.py` 双守卫 | ✅ 遵守 |
| 不实现 IGES/glTF/3MF/DXF provider | `src/mycad/formats/providers/` 仅两个文件 | ✅ 遵守 |
| priority 语义（默认 100 / 取小值 / 相同即 `ProviderConflictError`，不隐式覆盖） | `registry.py:34-45` + `:58`；`base.py:40` | ✅ 遵守 |
| 导入三级枚举仅定义、无返回导入结果的产品路径 | `base.py:44 target: Literal["shape","xcaf"]`（xcaf 仅预留字面量）；三级枚举随 ADR 文字定义 | ✅ 遵守 |

### 3.5 ADR 与计划的其余一致性抽查

- ADR-004（MCP 只决策不实现）：仓库零 `mcp` 依赖（`pyproject.toml:15-18`）、
  `test_scope_audit.py:27-43 FORBIDDEN_IMPORT_ROOTS` 含 `mcp`/`urllib`/`requests`/`http`/`socket`
  并由 `test_no_forbidden_imports` + 反向自证守；ADR-004 §8 显式出现 "A19" 字样
  （计划 T4 要求的审计锚点），`test_adr_docs.py:55` 断言该 token 在场。✅
- ADR-006（平台分层 + 偏离 ①）：`## 基线偏离` 段记录 conda→pip+uv 的主路径改动，
  依据 E1/E11；`test_adr_docs.py:134` 锁定全 ADR 集 `## 基线偏离` 恰好两处且只在
  ADR-001/ADR-006。✅
- 偏离计数恒为 2（ADR-001 偏离②、ADR-006 偏离①），与计划 `:263` 的 #round11-NB5
  规定一致；`version` 字段与 `undo_compensation` 字段被 ADR-002 `:25` / ADR-001 `:20`
  明确声明为「协议增强、不计入偏离」。✅

---

## 4. 研究台账 A1–A20 处置核对

来源：`.omo/drafts/phase0-mvp-research-ledger.md:55-78`。处置口径 = ①阶段 0 落地，或
②在 ADR / 计划 `### Must NOT have` / `### 显式延期需求登记` 中显式处置。

| # | 假设 | 处置方式 | 落点证据 | 状态 |
|---|---|---|---|---|
| A1 | 几何 API 选 build123d 0.11.1，精确 pin，geom 层保留互换 | 落地 | `pyproject.toml:16`；`src/mycad/geom/kernel.py:58 assert_b123d_version`；`tests/geom/test_kernel_version.py` | ✅ 落地 |
| A2 | pip+uv 主路径，conda 降为离线备选 | 落地 + ADR 记录为偏离 ① | `uv.lock`；`README.md:117-122` 离线附录；`ADR-006 ## 基线偏离` | ✅ 落地 |
| A3 | Python 3.12 | 落地 | `pyproject.toml:8 >=3.12,<3.15`；`ci.yml:21 python-version: "3.12"` | ✅ 落地 |
| A4 | undo = 删命令 + 历史重放；批失败快照回滚 | 落地 | `bus.py:127-165`、`:196-235`；`ADR-001 §2/§3` | ✅ 落地 |
| A5 | 存档 = JSON（元数据 + 有序命令），brep 不内嵌（含 #round10-NB6 覆盖更新） | 落地 | `schema_v1.py`、`persistence.py`；`ADR-002 §1/§8/§9` | ✅ 落地 |
| A6 | 拓扑引用纪律：禁裸索引，用几何谓词 | 落地 | `src/mycad/core/selectors.py`（`FaceSelector`/`EdgeSelector`，无位置/索引字段）；`schema_v1.py:165-213` 闭合解码；`tests/geom/test_face_selectors.py`、`test_edge_selectors.py` | ✅ 落地 |
| A7 | 阶段 0 无 LLM，agent 包只留 Plan 数据结构 + 状态机 | 落地 | `src/mycad/agent/plan_types.py:18 __all__ = ["InvalidPlanTransition","Plan","PlannedCommand"]`（纯再导出）；`core/plan.py:19-30` 六态六边；`tests/plugins/test_agent.py` | ✅ 落地 |
| A8 | 阶段 0 无 Qt 依赖 | 落地（机器化禁令） | `FORBIDDEN_IMPORT_ROOTS` 含 PySide6/PyQt6/PyQt5/vtk；`FORBIDDEN_DISTRIBUTIONS` 同 | ✅ 落地 |
| A9 | Apache-2.0 + SPDX 头 + NOTICE 第三方归属 | 落地 | `LICENSE`；`tests/test_spdx.py`（前两行逐字 + 反向自证）；`NOTICE` 115 行；`tests/test_notice.py` 6 例 | ✅ 落地 |
| A10 | CLI 命令语言 ASCII 英文，中文留给 UI | 落地 | `commands/grammar.py` + `specs.py` 的 `verb_aliases=("box","cylinder","extrude","revolve","hole","hole-pattern","fillet","cut")`；`label_zh` 仅作显示名储备 | ✅ 落地 |
| A11 | ruff + basedpyright + pytest，严格类型、无 any | **部分落地** | 工具链齐备（`pyproject.toml:23-34`、`pyrightconfig.json`）；但「零类型抑制」不变量实际被破坏且守卫空转（**P1**），ruff 规则集偏离 T1 原文（**P2**） | ⚠️ PARTIAL |
| A12 | git init + GHA 三 job 矩阵 | 落地（CI 就绪未实测，已记录） | `ci.yml:14`；`tests/test_ci_workflow.py`；遗留见 `task-1` §4 与 `task-11` D15 | ✅ 落地 |
| A13 | importlib.metadata entry points + manifest 契约 | 落地 | `plugins/discovery.py`、`manifest.py`、`types.py`；`plugins_examples/mycad_plugin_demo/` | ✅ 落地 |
| A14 | MCP 定位（server / 计划面工具 / plan_id / confirmation_token），阶段 0 仅出 ADR | 显式处置 | `ADR-004 §1-§7`；阶段 0 零 mcp 依赖（机器化守） | ✅ ADR 处置 |
| A15 | PLM 缝：Document metadata + pre/post command & save 事件 | 落地 | `document.py:102 METADATA_KEYS`；`signals.py:21-28` 五信号；`persistence.py:117/:135` saving/saved | ✅ 落地 |
| A16 | CAE 缝：mass properties + 可调弦差 tessellation + NamedGroup | 落地 | `kernel.py:106 mass_properties`、`:111 tessellate(linear_tolerance_mm, angular_tolerance_deg)`；`core/groups.py:18 NamedGroup`；`schema_v1.py:93` 存档侧 named_groups | ✅ 落地 |
| A17 | 格式注册表对齐 DE_Wrapper + 免费优先序列 + 商业墙 | 落地（缝）+ ADR 记录序列 | `formats/base.py`、`registry.py`；`ADR-005 §1/§3/§4/§5` | ✅ 落地 |
| A18 | 平台分层 T1/T2/T3 + glibc≥2.31 + 申威不纳入 | 显式处置 | `ADR-006 §1-§6` | ✅ ADR 处置 |
| A19 | 国产 LLM 路径（DeepSeek/通义/Ollama，不绑境外 API） | 显式延期登记 | 计划 `### 显式延期需求登记` 末行（status=accepted/future）；`ADR-004 §8` 明文含 "A19"，`test_adr_docs.py:55` 锁该 token | ✅ 显式延期 |
| A20 | 交付 ADR-001..006 六份 | 落地 | `docs/adr/` 六文件；`tests/test_adr_docs.py:104` | ✅ 落地 |

**A1–A20 静默缺失：0 条。** 唯一非绿是 A11（PARTIAL，根因即 P1/P2）。

---

## 5. R1–R18 风险缓解核对

来源：`.omo/drafts/phase0-mvp-research-ledger.md:178-197`。

| # | 风险 | 缓解 / 接受 | 落点证据 | 状态 |
|---|---|---|---|---|
| R1 | OCP conda 包对 Py3.12 滞后 | 台账自身已标注「已被 E1 消解」，转为 R13 | 台账 `:178`；`ADR-006` 以 wheel 矩阵替代 | ✅ 已消解（显式） |
| R2 | build123d 0.x API breaking | 精确 pin + geom 层收口 | `pyproject.toml:16`；`test_layering.py::test_src_has_no_backend_imports`；`geom/kernel.py:58` 版本断言 | ✅ 已缓解 |
| R3 | 选择器重放脆弱（TNP） | A6 谓词纪律 + golden 回归 + 重放失效显式报错 | `core/selectors.py`；`bus.py:161-164`；`tests/test_acceptance_flange.py:147`（Group B 改参重放无 `TopologyReferenceError`） | ✅ 已缓解 |
| R4 | 阶段膨胀 | Must NOT have 清单 + 机器化范围审计 | 计划 `:49-57`；`tests/test_scope_audit.py` 14 例（四组各带反向自证） | ✅ 已缓解 |
| R5 | 无 git | git init 完成 | HEAD `feecf03`，22 commits | ✅ 已关闭 |
| R6 | OCCT 视口嵌入（阶段 1）可能延期 | 阶段 0 只交付 tessellation 数据接口，Viewport 后置 | `kernel.py:111 tessellate`；`ADR-001 基线偏离 ②(2)`；计划显式延期登记 F-MOD-02 行 | ✅ 显式后置 |
| R7 | 商业内核格式无开源读路径 | 只做接口 + 商业插件生态位，不承诺时间表 | `ADR-005 §4`；`COMMERCIAL_FORMATS` 机器化守 | ✅ 已缓解 |
| R8 | LoongArch/信创生态 | T3 go/no-go 推迟至阶段 1 末 spike，最坏降级为战略路线 | `ADR-006 §5`、`Consequences` 末段 | ✅ 显式接受 |
| R9 | 插件全信任 | manifest 权限声明 + 文档告知，v1 不做沙箱 | `ADR-003 §6`；`manifest.py:131-140`；计划 T9 安全文档条 | ✅ 显式接受 |
| R10 | MCP 远程确认 UX | 阶段 2 设计；阶段 0 只锁「任何传输面不得绕过确认门」 | `ADR-004 §4` + `Consequences` 第 2 条 | ✅ 显式延期 |
| R11 | DWG 等闭格式合规雷区 | 不碰逆向库；ODA 转换器由用户自装 | `ADR-005 §5` | ✅ 已缓解 |
| R12 | 三个补充点导致范围蔓延 | 阶段 0 = 定缝 + ADR + 最小可验证实现 | 计划 Scope + C7/C8/C9；六份 ADR | ✅ 已缓解 |
| R13 | OCP wheel 要求 glibc≥2.31，UOS V20 桌面版不可直装 | ADR-006 声明支持基线，旧版列已知限制 | `ADR-006 §3`；`test_adr_docs.py:65` 锁 `glibc`/`2.31`/`manylinux_2_31` token | ✅ 已缓解 |
| R14 | build123d 0.x 每数个 minor API breaking | 精确 pin + 升级走独立 spike | `pyproject.toml:9-16` 注释写明 pin 理由 | ✅ 已缓解 |
| R15 | 双 OCCT 运行时冲突（pythonocc vs OCP） | 阶段 0 不引入 pythonocc-core/CadQuery（机器化禁令）；阶段 1 绑定统一决策列为路线图 | 计划 `:56` Must NOT have 点名 R15；`FORBIDDEN_IMPORT_ROOTS` 含 `OCC`、`cadquery`；`FORBIDDEN_DISTRIBUTIONS` 含 `pythonocc-core`；计划 `:548` 路线图锚点 | ✅ 已缓解（见 P4：台账提到的「ADR-007 占位」未落地，但已被计划「恰好 6 份 ADR」+「不写阶段 1–3 产品锚点」覆写，非静默缺失） |
| R16 | MCP SDK v1→v2 大改 | ADR-004 写明「落地锁主版本 / 工具面经 Bus 计划面 / 确认经显式 token」三不变量 | `ADR-004 §5` | ✅ 已缓解 |
| R17 | 全量重放性能上界 | 显式接受（法兰级毫秒），brep 快照缓存列 v2 演进口 | `ADR-001 §2` + `Consequences`；`ADR-002 §9` | ✅ 显式接受 |
| R18 | 国内网络直连 PyPI 大 wheel 超时 | 安装文档内置清华/阿里镜像，CI 用官方源 | `README.md:101-115`；`ci.yml` 不配镜像 | ✅ 已缓解 |

**R1–R18 静默缺失：0 条。**

---

## 6. 已知偏差记录的诚实性核验（T11 D8–D15 与 §T11-pre）

计划要求本次审计核验 `.omo/evidence/task-11-phase0-mvp.md` 的偏差记录是否属实、是否与
代码现状一致。逐条核验结论如下（**全部属实**）：

| 记录 | 核验方法 | 结论 |
|---|---|---|
| **§T11-pre 缺口 1：`uv tree --no-dev` 不过滤 dev 依赖** | `pyproject.toml:20-22` 的注释逐字说明「PEP 735 group, not an extra: `uv tree --no-dev` only filters dependency groups」；`:23 [dependency-groups]` 已就位，`[project.optional-dependencies]` 已不存在；`ci.yml:24 uv sync --frozen`（已去 `--extra dev`）；提交 `fecd081` 独立记录该变更 | ✅ 属实。根因正确：`--no-dev` 对 PEP 735 组生效、对 extra 无效；若不修，`packaging`（`FORBIDDEN_DISTRIBUTIONS` 成员）会混入闭包使 `test_runtime_closure_clean` 必红 |
| **§T11-pre 缺口 2：`.gitignore` 缺六个验收产物条目** | `.gitignore` 现含六条根锚定规则；计划 `:495` 确曾声称「这些路径同时已被 T1 `.gitignore` 逐行忽略」而 T1 未交付 | ✅ 属实，修复到位 |
| **§T11-pre 缺口 3：OCCT 许可证双行归属** | `NOTICE:27-49` 确为双行归属：`:33` `cadquery-ocp-novtk (OCP binding code) Apache-2.0`；`:36` `Open CASCADE Technology 7.9.3 (bundled) LGPL-2.1 with the Open CASCADE exception`；`:38-49` 同时写明「wheel 捆绑 46 个 OCCT 原生库」「wheel 不附 OCCT 许可证文本」这一取证边界、独立原生库/动态加载边界；`tests/test_notice.py:47 test_occt_has_both_attributions` 断言两项同时在场 | ✅ 属实。决策诚实：METADATA 实测 Apache-2.0 覆盖的是绑定代码，上游 OCCT 为 LGPL-2.1+例外；只写 Apache-2.0 确属低报分发义务。改为「两项在场」断言而非「实测字符串属 LGPL 族」单值比对，是对上游事实的正确响应，不是放水 |
| **D8：`requests` 不能列入闭包违禁名单** | `tests/test_scope_audit.py:52-56` 注释逐字记录同一理由；`FORBIDDEN_DISTRIBUTIONS`（`:57-58`）确实**不含** `requests`；`FORBIDDEN_IMPORT_ROOTS`（`:38`）确实**含** `requests`，由 `test_no_forbidden_imports` + 反向自证强制 | ✅ 属实。理由成立：`requests` 是 build123d 0.11.1 的直接运行依赖（台账 E1 原文已列），禁入闭包等于禁掉唯一几何后端；且计划 T11 的 NOTICE 规格自身要求对 requests 做归属，与「闭包禁用」自相矛盾。实际落点「MyCAD 代码不得 import」是可执行且更严的约束 |
| **D9：闭包违禁名按完整分发名精确比对** | `test_scope_audit.py:49-51` 注释 + `:60 REQUIRED_DISTRIBUTIONS={build123d, cadquery-ocp-novtk}`；`:231 FORBIDDEN_DISTRIBUTIONS & closure == set()` 为集合交，非子串 | ✅ 属实，且逻辑必要（子串匹配会让 `cadquery` 命中必须在场的 `cadquery-ocp-novtk`） |
| **D10：商业格式按点号后缀 + 文件名 stem 匹配** | `:61-66` 注释与常量 | ✅ 属实（`sat`/`nx` 裸子串会命中 saturate/linux） |
| **D11：`lib3mf` 实测 BSD-3-Clause** | NOTICE 归属表记录实测值与证据路径 | ✅ 属实（证据路径在场，可复核） |
| **D12：审计文件以字符串拼接规避自命中** | `test_scope_audit.py:70-80`（`"document.import" + "_step"`、`"import" + "_step"`）与 `tests/formats/test_guards.py` 同约定 | ✅ 属实 |
| **D13：`git ls-files` 八进制转义需 `-z`** | `test_scope_audit.py:266 test_tree_boundaries_docs_baseline_unchanged` + `:275` 反向自证 | ✅ 属实 |
| **D14：`git status --porcelain` 折叠未跟踪目录需 `-uall`** | 本审计独立复现：`git status --porcelain` 对未跟踪目录确实折叠 | ✅ 属实 |
| **D15：Windows / 三 CI job 无远端可跑，标「就绪未实测」** | 仓库无 GitHub 远端；`task-1` §4 与 `task-11` D15 均如实标注并禁止下游虚报 | ✅ 属实，记录诚实 |

**核验总结：D8–D15 与 §T11-pre 三处缺口的记录全部与代码现状一致，无粉饰、无不实。**
特别地，计划 F1 点名核验的三项（`requests` 闭包豁免、OCCT 双行归属、`uv tree --no-dev`
dev 过滤）均经独立取证确认，理由链完整且结论正确。

---

## 7. 发现的问题清单

### P1（**阻断性 / 导致 REJECT**）零类型抑制不变量：守卫空转 + 3 处真实违规

**位置**
- 守卫：`tests/test_layering.py:106-132`（HEAD `feecf03` 版本），关键行 `:111` 与 `:117`
- 违规点：
  - `tests/core/test_groups.py:31` — `group.name = "other"  # type: ignore[misc]`
  - `tests/core/test_groups.py:52` — `NamedGroup(...)  # type: ignore[arg-type]`
  - `tests/core/test_geometry_types.py:28` — `box.xmin = 99.0  # type: ignore[misc]`

**被违反的计划条款**
- `.omo/plans/phase0-mvp.md:81`（Verification strategy）：「`# type: ignore`/`# pyright: ignore`
  全仓唯一合法位置=`tests/typing/` 反例目录……`src/**` 与其余 `tests/**` 零 ignore」
- `.omo/plans/phase0-mvp.md:174`（T1 豁免规则 #round9-9）：「`tests/test_layering.py` 增加
  AST 断言：全仓 ignore 注释所在文件路径必须以 `tests/typing/` 为前缀（**反向自证：在 src
  放一条 ignore 必须变红**）」

**技术根因**
```
tests/test_layering.py:111    suffixes = ("py",)
tests/test_layering.py:114    for path in REPO.rglob("*"):
tests/test_layering.py:117        if path.suffix not in suffixes:
tests/test_layering.py:118            continue
```
`pathlib.Path.suffix` 返回**带点**的 `".py"`，而白名单元组是**不带点**的 `"py"`，因此
`".py" not in ("py",)` 恒为 True，循环对每个文件立即 `continue`。

实测（只读复算，本审计执行）：
```
$ python3 -c "from pathlib import Path; print(repr(Path('a.py').suffix))"
'.py'
$ # 用 HEAD 版守卫的筛选逻辑统计实际被扫描的文件数
files actually scanned by HEAD guard: 0
```
**该测试扫描 0 个文件，断言恒为真，自 T1（提交 `9d99fb7`）起从未生效过。** 它在 795 条
收集用例中长期显示 PASS，构成虚假绿灯。

**后果**
1. 计划 `:81`/`:174` 的硬不变量实际已被破坏（上列 3 处），无人发现。
2. `AGENTS.md` 的 ANTI-PATTERNS 条目「❌ 加 `# type: ignore` → `test_no_type_ignore_or_pyright_ignore_sites` 拦」
   在 HEAD 上是**不成立的陈述**。
3. 这 3 处 `# type: ignore` 会被 basedpyright 正常采纳（默认 `enableTypeIgnoreComments`），
   所以「basedpyright strict 0 errors」这条证据的含义被削弱——它是在 3 处抑制之后取得的。
4. 计划明文要求的**反向自证测试缺失**：`tests/test_layering.py` 中没有任何
   `reverse_self_proof` 用例（对比 `tests/test_scope_audit.py` 的四组均配反向自证）。
   正是反向自证的缺席让这个空转持续了 11 个 todo。

**修复方向（供 T1/T6 回修参考，本审计不执行）**：`rglob("*.py")`、needles 以字符串
拼接避免自命中、补一条反向自证用例；并决定这 3 处抑制是改为 `tests/typing/` 对照文件、
还是改写断言方式（例如 `pytest.raises(...)` + `cast` 而非 ignore 注释）。

> 审计时点观察（不计入问题，仅作记录）：本次审计与 Final wave 其他只读/修复活动并行，
> 工作树在审计过程中出现一批未提交修改（先是 `M tests/test_layering.py`，其 diff 恰好把
> `REPO.rglob("*")` + `suffixes` 改为 `REPO.rglob("*.py")` 并改用拼接 needles，即对 P1
> 第一半「守卫空转」的修复；随后又出现 `M tests/core/test_groups.py`、
> `M tests/core/test_geometry_types.py`、`M tests/core/test_selectors.py` 以及
> `M src/mycad/cli/{__main__,plans,session}.py`、`M src/mycad/core/{groups,handlers}.py`）。
> 这些均为**未提交**的工作树状态，可能是并行的 P1 回修。F1 的全部判定一律以 HEAD
> `feecf03` 为基准，故 P1 在本次审计中成立；若回修提交后同时解决「守卫有效化 + 3 处真实
> 违规清零 + 补反向自证」三点，P1 可在复审中关闭。

### P2（中）ruff 规则集偏离 T1 原文，且无任何证据文件记录

- 位置：`pyproject.toml:72-83`
- 计划 `:131` 原文：「ruff 配置：target-version py312，select=`E,F,I,N,UP,B,SIM,RET,PT,PL`，
  line-length=100，known-first-party=`mycad`」
- 实际：`select = ["E","F","W","I","B","UP","C4"]`，并额外 `ignore = ["E501"]`
- 差异：**缺失** `N`(pep8-naming)、`SIM`(flake8-simplify)、`RET`(flake8-return)、
  `PT`(flake8-pytest-style)、`PL`(pylint)；**新增** `W`、`C4`；**新增** `E501` 全局 ignore
  （计划未授权任何 ruff ignore，且 line-length=100 本身就是靠 E501 落地的）
- 严重性：这不是空转（`target-version`/`line-length`/`known-first-party` 均与计划一致，
  ruff 确实在全树执行），但 5 条规则族被静默摘除、1 条规则被静默豁免。
- **记录缺失**：`.omo/evidence/task-1-phase0-mvp.md:103-104` 的「## 5. Deviations from plan
  spec」写的是「**None of substance.**」，仅列了 `.omo` 排除与异常字段检查方式两条；
  本偏差未被提及。全部 11 份 task 证据文件中亦无任何处记录（本审计已 grep 核实）。
  按计划的留痕纪律，这属于**未记录偏差**。

### P3（低）pytest addopts 缺计划钉死的 `--ignore=tests/typing`

- 位置：`pyproject.toml:46-48`（`addopts = "-ra"`）
- 计划 `:131`/`:174` 要求 `addopts = "-ra --ignore=tests/typing"`，并明文称其为「双保险」
  （另一重保险 = 文件名禁用 `test_*` 前缀）
- 现状：双保险只剩一重。实测无功能后果——`tests/typing/expect_errors.py` 文件名不匹配
  `test_*.py`，pytest 不会收集（795 条收集用例中无该文件）。但该文件第 23 行是**运行时
  必失败代码**，一旦将来有人在该目录加一个 `test_` 前缀文件，整套件会被污染。
- 同样**未在任何证据文件中记录**。

### P4（信息 / 不计为缺陷）研究台账 R15 提到的「ADR-007 占位」未落地

- 台账 `:194` 原文：「ADR-007（阶段 1 预备）占位记录」；`docs/adr/` 实际只有 001–006。
- 判定为**非静默缺失**：计划 Must have 第 10 项把阶段 0 的 ADR 集合钉死为「6 份」，
  Must NOT have `:57` 又规定「不写任何阶段 1–3 的产品代码锚点（接口只在 ADR 文字中描述）」，
  `tests/test_adr_docs.py:104` 机器化断言「恰好六个编号文件」。即台账的 ADR-007 想法已被
  计划显式覆写。**R15 风险本体的阶段 0 缓解（不引入 pythonocc-core/CadQuery）已落地并机器化
  强制**（见 §5 R15 行）。此条仅作台账与计划的文字不一致备案。

### P5（信息 / 不计为缺陷）`AGENTS.md` 的 CLI 描述已过时

- `AGENTS.md` 的 COMMANDS 段与 NOTES 段称「`mycad validate/commands/plugins` 阶段 0 尚未
  实现（`cli/__main__.py` 触发 not-implemented 退出码 2）」。
- 实际 HEAD：`src/mycad/cli/__main__.py:71-88` 三个子命令均已完整实现并有测试
  （`tests/cli/test_validate.py`、`tests/cli/test_commands_plugins.py`），由 T10b/c
  （提交 `58493b6`、`014bcd5`）落地。AGENTS.md 文字停留在 T10 之前。
- 不属计划合规问题（AGENTS.md 不是计划交付物），但会误导后续代理，建议顺手更新。

---

## 8. 判定依据汇总

| F1 子项 | 结果 |
|---|---|
| 1. Must have C1–C10 覆盖映射 | COVERED 9 / PARTIAL 1 (C1) / MISSING 0 |
| 2. 8 条命令 id 逐字比对 | 8/8 一致，零差异 |
| 3. ADR-001..006 存在性与一致性 | 六份齐备；四处重点抽查（001 写入路径与重放、002 审计六字段、003 api 主版本门控、005 商业墙）全部一致 |
| 4. A1–A20 处置 | 18 落地 + 2 ADR/延期显式处置；A11 PARTIAL；**静默缺失 0** |
| 5. R1–R18 缓解 | 18/18 有缓解或显式接受；**静默缺失 0** |
| 附加：T11 D8–D15 与 §T11-pre 记录诚实性 | 全部属实，与代码现状一致 |

**最终结论：REJECT。**

唯一阻断项是 P1：一条计划硬不变量的守卫自 T1 起即为空转（实测扫描 0 文件），且该不变量
在 `tests/core/` 下已有 3 处真实违规，同时计划明文要求的反向自证用例缺失。P2/P3 为
未记录的配置偏差，应在同一轮回修中补记或补齐。

回修完成后建议重跑 F1 的第 1 项（C1 行）与本节 P1–P3，其余四项（命令 id、ADR、A、R）
已 CONFIRMED，无需重跑。

---

# 复查（HEAD=dc2cdac）

**更新后结论：APPROVE**

复查基准：`dc2cdac`（较上轮审计基准 `feecf03` 多 5 个提交）。日期 2026-10-11。
审计人仍为 F1 只读审查代理；本轮同样只写本文件，未修改仓库任何其他内容
（复查全程 `git status --porcelain` 仅有 `M .omo/evidence/final-2-phase0-mvp.md`
这一处来自并行 F2 会话的改动，与本审计无关）。

范围严格限定为上轮遗留的三件事，**未重做**已 CONFIRMED 的四项（Must have 覆盖的
C2–C10、8 条命令 id 逐字比对、ADR-001..006 一致性、A1–A20 / R1–R18 处置）。

本轮复查的 5 个提交：

| commit | 主题 |
|---|---|
| `721cef2` | 修复空转的类型抑制守卫 + 打断 cli import 环 |
| `688d001` | `mycad commands` 改为真实插件发现 |
| `382955d` | README 镜像改写 `uv.lock` 的警示 |
| `3cd6b51` | `test_scope_audit` 加固（F4 发现的 Must-NOT 覆盖洞） |
| `dc2cdac` | 启用 N/SIM/RET + 记录仍关闭的两族 + 补 addopts + 清理 AGENTS.md |

---

## R1. P1 是否关闭 —— **已关闭**

### (a) 守卫是否真的在扫文件了

`721cef2` 把 `tests/test_layering.py:106-132` 的遍历改为：

```
-    suffixes = ("py",)
-    for path in REPO.rglob("*"):
-        if path.suffix not in suffixes:
-            continue
-        if "__pycache__" in path.parts:
+    for path in REPO.rglob("*.py"):
+        if "__pycache__" in path.parts or ".venv" in path.parts:
             continue
```

恒真的 `continue` 分支（`".py" not in ("py",)`）已整体删除。本审计用只读脚本复算当前
守卫的筛选逻辑：

```
files scanned by current guard: 164 | whitelisted: 1
```

上轮同样的复算结果是 `0`。守卫由**扫 0 个文件**变为**扫 164 个文件**（`tests/typing/`
下 1 个文件走白名单）。✅ 关闭。

另：上轮 P1 指出「计划 `:174` 要求的反向自证缺失」。本次未新增提交式反向自证用例，
但 F2 以计划 F2 条目要求的**活体反向注入**交付了等价证明——
`.omo/evidence/final-2-phase0-mvp.md:100-125` 记录 6 条注入探针，其中
`type-suppression`（向 `src/mycad/core/groups.py` 注入抑制注释）判红后还原判绿，并
明确写出「这一条在修复**之前**会是 FAIL（注入后守卫仍绿）」。该交付形式符合计划
F2「评审现场对每个守卫各做一次反向注入」的原文，反向自证要求视为已满足。✅

### (b) `tests/typing/` 以外的抑制注释是否归零

本审计独立扫描（不依赖被审测试）：

```
$ rg --glob '!.venv' --glob '!.omo' --glob '*.py' \
     -e '# type: ignore' -e '# pyright: ignore' -e '# pyright:' . | grep -v '^./tests/typing/'
（无输出）
```

✅ 归零。白名单内仅 `tests/typing/expect_errors.py:23` 一处，属 expect-error 语料，合规。

### (c) 修复方式是否诚实 —— **是，四处均无假修复**

**先排除两类典型假修复：**

- **没有扩白名单**：白名单分支仍逐字是 `rel.startswith("tests/typing/")`，
  未新增任何路径；实测走白名单的文件恰好 1 个。
- **没有弱化 needle**：needles 由
  `("# type: ignore", "# pyright: ignore", "# pyright:")` 改写为
  `("# type" + ": ignore", "# pyright" + ": ignore", "# pyright" + ":")`。
  三个表达式求值后与原字符串**逐字符完全相同**，改写的唯一目的是让守卫文件自身不再
  命中（与 `tests/formats/test_guards.py` 同约定）。检测能力零变化。

**四处违规点的处理，逐处判定：**

| # | 位置 | 处理方式 | 原测试语义是否保留 | 判定 |
|---|---|---|---|---|
| 1 | `tests/core/test_geometry_types.py:27` | `box.xmin = 99.0  # type: ignore[misc]` → `field = "xmin"` + `setattr(box, field, 99.0)` | 保留。断言体仍是 `pytest.raises(dataclasses.FrozenInstanceError)`；frozen dataclass 的 `__setattr__` 对 `setattr` 与直接赋值走同一路径，运行时行为完全一致 | ✅ 诚实 |
| 2 | `tests/core/test_groups.py:29` | 同上（`group.name`） | 同上 | ✅ 诚实 |
| 3 | `tests/core/test_selectors.py:41` | 同上（`fs.surface`） | 同上 | ✅ 诚实 |
| 4 | `tests/core/test_groups.py` 的 `test_named_group_list_inputs_become_tuples` | 连同 `src/mycad/core/groups.py` 的 `NamedGroup.__post_init__` 一并删除 | 见下方专项分析 | ✅ 诚实（附观察 N1） |

**关于 1–3 的「静态覆盖是否被偷偷降低」**：经变量名 `setattr` 后，basedpyright 不再对
该行做属性可写性检查。但这不构成覆盖下降——**原写法同样没有静态覆盖**：pyright/
basedpyright 对 `# type: ignore` 的处理是抑制该行**全部**诊断（不解析方括号内的错误码），
所以旧代码里的 `# type: ignore[misc]` 本就把该行的静态检查整条关掉了。两种写法的静态
覆盖同为零，而运行时断言（frozen → 抛 `FrozenInstanceError`）完整保留。三处均加了注释
说明为何绕道，没有掩饰。

**关于第 4 处（唯一需要专项判断的）**：被删的 `__post_init__` 做的是
`object.__setattr__(self, "faces", tuple(self.faces))` 式的 list→tuple 防御性归一化。
判定要点：

1. **提交信息的事实主张经核验属实。** 声称「every call site already passes tuples」。
   本审计独立枚举全部 `NamedGroup(` 构造点（`rg 'NamedGroup\(' src tests`）：src 侧
   **唯一**构造点是 `src/mycad/core/persistence.py:204`，其 `faces`/`edges` 在
   `:197-203` 由 `tuple(...)` 生成器表达式构造；tests 侧全部传元组字面量或默认值。
   删除 `__post_init__` 不改变任何现存调用点的行为。
2. **被删的测试只能靠违反类型契约才能触达。** 字段声明是
   `faces: tuple[FaceSelector, ...]`，所以该测试当初必须写 `# type: ignore[arg-type]`
   才能传 list。删掉一个「只有突破 basedpyright strict 才能进入的分支」的测试，不属于
   为过守卫而削减有效覆盖。
3. **文档同步诚实。** `groups.py` 的 docstring 由「accept any iterable at construction；
   normalised to tuples」改为「are tuples so the group stays immutable；the JSON loader
   materialises them as such」——如实描述了收紧后的契约，没有留下与代码不符的旧表述。

因此第 4 处不是假修复。但它确实是**为通过测试卫生守卫而改动了产品代码**，残留一条
行为差异，记为观察 N1（非阻断）。

### (d) 全量测试现状

```
$ uv run pytest -q
795 passed, 1 skipped, 5 errors in 117.62s
```

**5 个 error 全部是本审计沙箱的产物，不是仓库缺陷，更不是本轮回归。** 均来自
`tests/plugins/test_demo_installed.py` 的 class 级 fixture，失败原因逐字为：

```
pip install -e failed (1): ERROR: Could not install packages due to an OSError:
[Errno 30] 只读文件系统: '…/.venv/lib/python3.12/site-packages/_editable_impl_mycad_plugin_demo.pth'
```

F1 以只读审查员身份运行，`.venv/` 对本进程只读，该 fixture 需要 editable 安装 demo 插件
故无法建立。**F1 不以此主张任何失败**；该用例的绿由 F2/F3 在可写环境中负责。
收集总数 801（上轮 795），增量 +6 = 新增 1 条 `commands` 插件可见性测试、5 条
`test_scope_audit` 新测试、1 条 `test_types` 新测试，减去被删的 1 条 NamedGroup 用例。

---

## R2. P2 / P3 是否关闭 —— **均已关闭**

### P3（`addopts` 缺 `--ignore=tests/typing`）—— 已修

`pyproject.toml:46-49` 现为：

```toml
# tests/typing/ holds deliberately-failing expect-error sources. The file
# names already miss the test_*.py pattern; this is the second belt.
addopts = "-ra --ignore=tests/typing"
```

与计划 `:131`/`:174` 的「双保险」表述一致。✅ 关闭。

### P2（ruff 规则集静默偏离）—— 已关闭

`pyproject.toml:69-105` 现状与计划 `:131` 原文的逐族对照：

| 规则族 | 计划 `:131` | `dc2cdac` 后 | 本审计判定 |
|---|---|---|---|
| `E` `F` `I` `UP` `B` | 启用 | 启用 | 一致 |
| `N` | 启用 | **已启用**（`N818` 单独 ignore） | 合规，理由成立（见下） |
| `SIM` | 启用 | **已启用** | 补齐 |
| `RET` | 启用 | **已启用** | 补齐 |
| `PT` | 启用 | 仍关闭 | 仍偏离，但**已书面记录** |
| `PL` | 启用 | 仍关闭 | 仍偏离，但**已书面记录** |
| `W` `C4` | 计划未列 | 启用 | 计划外增强，无害 |
| `E501` | 未授权 ignore | 仍 ignore | 合规，理由成立（见下） |

**本审计对两条 carve-out 理由做了独立验证（不采信证据文件的转述）：**

**① `N818` 的理由成立。** 用隔离配置实测全树：

```
$ uv run ruff check --isolated --select N818 --no-cache src tests scripts
N818 Exception name `InvalidPlanTransition` should be named with an Error suffix
   --> src/mycad/core/exceptions.py:110:7
Found 1 error.
```

全仓**恰好 1 处**命中。该类名确实被计划钉死——计划 `:135` 的 15 条异常全集，第 10 条
逐字为 `` `InvalidPlanTransition(from_status, requested)` ``（本审计直接读取该行核对）；
且 `tests/test_exceptions.py:11-21` 的 `EXPECTED_NAMES` 列表含字符串
`"InvalidPlanTransition"`，`:35` 断言子类恰好 15 个。**改名 = 同时违反计划 `:135` 与
`test_exceptions.py` 的名字集合锁定。** 用一条全局 `N818` ignore 换取 `N` 族其余规则
全部生效，是在计划约束下的唯一可行解，且避免了计划禁止的 per-file ignore。理由属实。

**② `E501` 的理由成立。** 同样隔离实测：

```
$ uv run ruff check --isolated --select E501 --line-length 100 --no-cache src tests scripts plugins_examples
src/mycad/commands/grammar.py:45:101: E501 Line too long (129 > 100)
src/mycad/commands/grammar.py:47:101: E501 Line too long (275 > 100)
tests/cli/test_qa.py:22:101:          E501 Line too long (125 > 100)
tests/cli/test_qa.py:23:101:          E501 Line too long (271 > 100)
Found 4 errors.
```

**恰好 4 处**，与声明一致。逐处核对上下文（本审计直接读源文件）：
- `grammar.py:42-50` 是模块 docstring 的 `Examples (each has a parse -> to_cli -> parse
  round-trip test)::` 代码块，45/47 两行分别是 `hole …` 与 `hole-pattern …` 的**规范
  CLI 命令行**；
- `test_qa.py:19-26` 是 `FLANGE_SEQUENCE` 三引号脚本夹具，22/23 两行是同样的两条命令。

CLI 文法是**一行一命令**（计划 T3/T10 的 grammar 规则），折行会让这四行变成语法错误的
示例/夹具。「全部是逐字引用的 CLI 命令行」的说法属实，不是为掩盖散落的长行而设的
全局豁免。

**③ `PT`/`PL` 仍关闭，但记录已到位，且数字经独立复核无误。**

```
$ uv run ruff check --isolated --select PL --no-cache --statistics src tests scripts
103  PLR2004  magic-value-comparison
 20  PLC0415  import-outside-top-level
  5  PLR0911 / 4 PLR0912 / 2 PLR0913 / 2 PLR0917 / 1 PLR1730 / 1 PLC0207
Found 138 errors.

$ uv run ruff check --isolated --select PT  --no-cache --statistics src tests scripts
10 PT001 / 8 PT018 / 2 PT011 / 1 PT012      Found 21 errors.
```

`pyproject.toml:95-98` 的注释写「PL alone reports 138 findings, 103 of them PLR2004」，
`.omo/evidence/final-2-phase0-mvp.md:205-206` 写「PT 21 处，多为 PT001 与 PT018」「PL
138 处，其中 103 处是 PLR2004」——**与本审计实测逐数字吻合**，无夸大。PLR2004 命中的
确实是 `assert len(rows) == 9` 这类「字面量本身就是断言内容」的测试代码，为其做常量提取
无正确性收益。

**P2 的实质是「偏离 + 零记录」。** 现在偏离同时写在 `pyproject.toml` 的配置注释（代码
近处）与 `final-2` 的偏差表（证据链），符合计划的留痕纪律；且 5 族中已补回 3 族。
**P2 关闭。** 残留事项记为观察 N2（`PT`/`PL` 仍与计划 `:131` 不符，属「已记录未消解」，
建议由计划所有者正式接受或排入阶段 1）。

### C1 判定更新

上轮因 P2/P3 将 C1 判为 **PARTIAL**。现 `N`/`SIM`/`RET` 已补、`addopts` 已补、两条
carve-out 理由经独立验证成立且已双处留痕——**C1 由 PARTIAL 上调为 COVERED（附已记录的
次要偏差 N2）**。

更新后的覆盖矩阵统计：**COVERED 10 / PARTIAL 0 / MISSING 0。**

---

## R3. 新增提交是否引入新的计划违规 —— **未引入**

### `688d001`（`mycad commands` 改为真实插件发现）—— 符合计划 `commands` 条目

计划 T10 的 `commands [--json]`（#NB4 输出契约）原文要求：

> 无插件时恰好 8 行/8 元素（该计数与 id 集合作快照测试）。**计数测试的环境隔离写死**：
> 在禁用 entry-point 发现的进程/monkeypatch 环境中运行（`build_app(discoverers=[])` 或
> monkeypatch entry_points 返回空……）；**另设一例装了 demo 插件的环境断言为 9 行且多出
> `demo.ping`**（两例显式区分"无插件环境/有插件环境"，禁止按当前环境隐式断言）。

计划把 `discoverers=[]` 的隔离明确限定在**计数测试**里，而修改前
`src/mycad/cli/__main__.py:70` 把它写进了**产品代码**，后果是插件贡献的命令在 REPL 里
可执行、被 `mycad plugins` 计数，却永远不会出现在 `mycad commands` 里——这既与
「列注册表」的子命令语义矛盾，也使计划要求的「9 行且多出 demo.ping」那一例在产品路径上
不可能成立。

`688d001` 的处理：产品侧改回 `build_app()`（真实发现），隔离下沉到两条计数测试
（`monkeypatch.setattr(EntryPointDiscoverer, "discover", _no_plugins)`），并新增
`test_commands_lists_plugin_contributions` 断言 9 行且含 `demo.ping`、verb 仍字典序。
该测试**经 `main()` 驱动而非直接构造 `CliSession`**，正好覆盖此前出错的接线层。

✅ **与计划 `commands` 条目的明文要求一致**，且是对一处真实偏离的修正，不是新违规。
（这也顺带消解了上轮 F1 记录的 P5：`dc2cdac` 同步删除了 AGENTS.md 中「validate/commands/
plugins 尚未实现、退出码 2」的过时表述。）

### `3cd6b51`（`test_scope_audit` 加固）—— 新增禁词**未超出**计划 Must NOT 范围

逐组把新增禁词回溯到计划条款，无一例外：

| 新增项 | 对应的计划条款 | 是否超范围 |
|---|---|---|
| `PySide2` `qtpy` `shiboken6` | Must NOT `:49`「无 PySide6/Qt/**任何 UI 代码**」 | 否（Qt 的其余入口） |
| `ollama` | Must NOT `:50` **逐字点名** `无 mcp/ollama 依赖` | 否（计划明文） |
| `openai` `anthropic` `langchain` `litellm` | Must NOT `:50`「**无真实 LLM 调用**」 | 否（该禁令的机械化，非新禁令） |
| `urllib3` `httpx` `aiohttp` `ftplib` | Must NOT `:50`「无网络调用代码」+ F4 §3「src 中无网络 import（**白名单：无，即全部禁止**）」 | 否 |
| 分发名 `restrictedpython` 等 | F4 §1 **逐字点名** `restrictedpython` | 否 |
| 格式 `dwg` | Must NOT `:53`「**不碰 DWG**/逆向库」 | 否（计划明文） |
| 格式 `sab` `x_b` `catpart` `catproduct` | Must NOT `:53` 的 `ACIS(sat)`/`Parasolid(x_t)`/`CATIA` 的其余扩展名拼写 | 否（同一厂商墙的别名） |
| `FORBIDDEN_CI_TOKENS = aarch64/arm64/qemu/loong` | Must NOT `:56`「**不做 aarch64/QEMU/龙芯 CI 任务**」 | 否 |
| `PACKAGING_PATTERNS` 增 `*.msi` `*.wxs` `*.deb` `*.rpm` | Must NOT `:55`「不做安装包（AppImage/Flatpak/**msi**）」 | 否（`wxs` 是产出 msi 的 WiX 源） |
| `OUT_OF_SCOPE_CONCEPTS` 17 个标识符 | 每条在源码注释里自带出处：inverse undo / brep 快照 / ElementMap（`:51`）、草图约束求解器（`:52`）、IGES·glTF·DXF·3MF provider（`:53`）、PLM BOM·mesher/INP（`:55`） | 否 |

**结论：零个禁词落在计划 Must NOT 之外。** 全部是对既有禁令的机械化落地——其中
`ollama`、`restrictedpython`、`DWG`、`msi`、`aarch64/QEMU/龙芯` 五项本就是计划**逐字
点名**却被原测试漏掉的，属补洞而非扩权。

被**有意排除**的项同样有记录且判断合理：`COMMERCIAL_FORMATS` 注释写明
「`prt` 与 `asm` 故意不列——作为整词仍与普通标识符冲突，且其厂商（NX、CATIA）已按名列出」；
`FORBIDDEN_DISTRIBUTIONS` 注释把 `requests` 的豁免理由扩写到同样经 build123d 传递进来的
`urllib3`，与上轮核验属实的 D8 口径保持一致（导入禁、闭包不禁）。

同时核验该提交没有放松任何既有断言：`test_runtime_closure_clean` 把
`pytest.skip("uv unavailable")` 改成 `assert result.returncode == 0`（**收紧**，消除了
uv 缺失时整条闭包断言静默退休的路径）；`test_backend_imports_are_confined_to_geom`
改为复用有反向自证覆盖的 `scan_forbidden_imports` 检测器（消除两份规则漂移）；
并新增 4 条反向自证/活性测试。方向全部是加强。

### `382955d`（README 镜像警示）—— 无违规

仅在 README 国内镜像段后追加 3 行警示：切索引后 `uv sync` 会改写 `uv.lock` 全部包的
`source` 与下载 URL（hash 不变），不要提交，CI 以 `--frozen` 安装会把三个 runner 钉死到
该镜像，同步后 `git checkout uv.lock` 还原。属计划 C1「安装文档含国内镜像配置（R18）」的
正确性补强；未触碰 T1 Must NOT 的「不改 README 现有许可段落」。✅

### `dc2cdac`（除 ruff 外的部分）—— 无违规

`AGENTS.md` 的过时 CLI 描述被更正（见上）；`src/` 侧的 6 处改动（`app.py`、
`validation.py`、`persistence.py`、`manifest.py`）均为启用 `SIM`/`RET` 后的机械修复
（如 `except OSError: pass` → `contextlib.suppress(OSError)`），不改变任何对外契约。✅

---

## R4. 复查遗留观察（均不阻断 APPROVE）

- **N1 — `NamedGroup` 失去 list→tuple 运行时归一化。** `721cef2` 删除
  `src/mycad/core/groups.py` 的 `__post_init__`。现存调用点全部传元组（已逐点核验），
  basedpyright strict 也会在所有带类型的调用点强制 `tuple[...]`，故当前无实际风险。
  但这是**为满足测试卫生守卫而改动产品代码**，留下一条行为差异：今后若有调用点绕过
  类型检查传入 list，`faces` 将是可变对象，`NamedGroup` 的不可变承诺在运行时不再自持。
  docstring 已如实改写，不构成隐瞒。建议阶段 1 评估是否以 `Sequence` 入参 + 显式
  `tuple()` 转换恢复防御，或保持现状并在 ADR-002 注明契约由静态检查承担。
- **N2 — `PT`/`PL` 仍与计划 `:131` 不符，属「已记录未消解」。** 理由（PLR2004 占 103/138、
  PT 多为纯风格）经独立复核成立，但偏离本身未消失。建议由计划所有者在计划中正式接受
  （补进一条偏差登记），避免下一轮审计重新把它当成新发现。
- **N3 — `3cd6b51` 提交信息有一处轻微夸大。** 信息称新的 `\b` 整词规则能挡住
  「`class JTProvider`」这种形状；实际 `\bjt\b` 不会匹配 `JTProvider`（全为词字符，
  中间无词边界）。其配套测试之所以通过，是因为夹具文件里同时含 `suffixes = ("jt",)`
  这一行。规则本身是有效收紧（确实挡住了 `import parasolid`、`SUFFIX = "dwg"` 等旧规则
  漏掉的形状），仅措辞需校正，不影响判定。
- **N4 — 本轮 F1 的 5 个 pytest error 是审计沙箱产物，不得计入仓库状态。** 详见 R1(d)。
- **N5 — 承接 F2 自列的遗留风险。** `final-2` 指出「守卫写了却一直空转」这一失败模式
  目前无人看守，建议给每个遍历型守卫加 `assert scanned > 0` 元断言。本审计认同：这正是
  P1 能潜伏 11 个 todo 的结构性原因，应排入阶段 1。

---

## R5. 复查结论

| 项 | 上轮（feecf03） | 本轮（dc2cdac） |
|---|---|---|
| P1 零抑制守卫空转 + 4 处违规 | **开启（阻断）** | **关闭**：守卫实扫 164 文件、违规归零、四处修复均诚实、F2 活体反向注入判红 |
| P2 ruff 规则集静默偏离 | 开启 | **关闭**：N/SIM/RET 补齐，E501/N818 两条 carve-out 理由经独立实测成立，PT/PL 偏离已双处留痕 |
| P3 `addopts` 缺 `--ignore=tests/typing` | 开启 | **关闭** |
| P5 AGENTS.md CLI 描述过时 | 信息项 | 已修正 |
| 新增 5 个提交是否引入新违规 | — | **未引入**；`688d001` 符合计划 `commands` 明文要求，`3cd6b51` 新增禁词零个超出 Must NOT 范围 |
| Must have 覆盖矩阵 | COVERED 9 / PARTIAL 1 / MISSING 0 | **COVERED 10 / PARTIAL 0 / MISSING 0** |
| 命令 id / ADR / A1–A20 / R1–R18 | 全部通过 | 未重做（已 CONFIRMED） |

**F1 最终结论：APPROVE。** 无 MISSING 项、无静默缺失、无新增计划违规。遗留 N1–N5 均为
非阻断观察，建议并入阶段 1 或由计划所有者正式接受。
