# Phase 0 / T4 evidence — Architecture decision records ADR-001…006 (Wave 1)

**Task**: T4 — six architecture decision records (MADR-lite, all Chinese) +
scripted acceptance test `tests/test_adr_docs.py` (+ 偏离基线说明).
**Plan**: `/media/sima/Data/projects/MyCAD/.omo/plans/phase0-mvp.md` lines 254–278.
**UTC timestamps**: started 2026-10-03T17:20:00Z, verified 2026-10-03T17:34:26Z.
**Environment**: Linux x86_64, Python 3.12.3, uv-managed `.venv` (no deps added).

## 1. Deliverables (exactly the scoped paths, nothing else)

| File | Content |
|---|---|
| `docs/adr/ADR-001-command-bus-and-history-replay.md` | 命令总线与历史重放；含偏离 ②（headless 投影，两项合并一个 `## 基线偏离` 段） |
| `docs/adr/ADR-002-document-archive-format-v1.md` | JSON 存档 v1（`.mc.json`、审计六字段、amendments、named_groups、迁移钩子、无导入节点） |
| `docs/adr/ADR-003-extension-points-and-plugin-api-versioning.md` | 扩展点与插件 API 版本（entry 组、#round7-4 manifest 定位算法、CommandContribution 契约） |
| `docs/adr/ADR-004-mcp-boundary.md` | MCP 边界（只决策不实现；plan_id / confirm_execute / A19 处置） |
| `docs/adr/ADR-005-format-provider-tiers.md` | 格式提供方分级（DE_Wrapper 对齐、priority/ProviderConflictError、导入三级、免费序列、商业墙、DWG） |
| `docs/adr/ADR-006-platform-tiering.md` | 平台分层（T1/T2/T3、glibc≥2.31 基线、龙芯 go/no-go）；含偏离 ①（conda→pip+uv，一个 `## 基线偏离` 段） |
| `tests/test_adr_docs.py` | 脚本化验收（pathlib + 正则，零第三方依赖；15 个测试用例） |

`git status` footprint check: only `docs/adr/` + `tests/test_adr_docs.py` (+ this
evidence file) added by T4; the three baseline docs untouched
(`tests/test_baseline_hashes.py` still green).

## 2. Per-ADR Decision one-sentence summaries (manual-QA channel)

- **ADR-001**: 一切改模型操作走唯一 Command Bus；undo/redo=删命令+全量重放（无 per-command inverse、无 brep 快照缓存），批事务=执行前快照整体回滚，重放引用失效显式报出命令 id；`undo_compensation="history_replay"` 为协议遵从而非偏离；同时以一个 `## 基线偏离` 段记录偏离 ②（Chat 确认投影为 CLI/JSON Plan + confirmed_by；"简单预览/简单 3D 预览"后置阶段 1，阶段 0 只交付 tessellation 数据接口）。
- **ADR-002**: 存档 v1 为 UTF-8 `.mc.json`（format/version/metadata/commands/named_groups，named_groups 恰 name/faces/edges 三键且不进重放序列），命令元素携带审计六字段 id/version/params/ordinal/timestamp_utc/confirmed_by 外加可选 amendments 修订留痕（不改写原 timestamp），version 校验+migrations.py 空钩子；阶段 0 无导入型历史节点，brep 快照缓存列为 v2 演进口。
- **ADR-003**: 扩展机制为 importlib.metadata entry points（`mycad.commands`/`mycad.formats`，预留 datum/inspect 文字），manifest 五字段 + `CURRENT_API_VERSION="1.0"` 主版本门控，#round7-4 定位算法（导入 `EntryPoint.module` 找固定名 `manifest`，三形态、按模块 memoize，损坏/缺失/主版本不符分报 manifest-error/missing-manifest/incompatible-api）；插件=全信任 Python；`CommandContribution(spec, handler_factory)` 为唯一命令贡献携带形式，BuiltinModelingHandler 兜底声明式命令，demo.ping 型必须自带 handler。
- **ADR-004**: MyCAD 作 stdio MCP server（只决策不实现，阶段 0 零 mcp 依赖）：工具面=只读查询+计划面五工具，状态用显式 plan_id 句柄，`confirm_execute(plan_id, confirmation_token)` 的 token 只能由产品侧用户交互产生；落地时锁 MCP Python SDK 主版本并优先用规范 elicitation（InputRequiredResult）承载确认；A19 国产 LLM 路径（DeepSeek/通义云端、Ollama 本地、OpenAI 兼容抽象、不绑境外 API）为 accepted/future 假设，阶段 0 无任何 LLM/网络/API 调用代码。
- **ADR-005**: FormatProvider 注册表对齐 OCCT 7.8 DE_Wrapper 的 name×vendor 模型并加 priority 整数（默认 100 取小值，同 priority 扩展名重叠抛 ProviderConflictError）；导入三级 DUMB_SOLID/ASSEMBLY_WITH_ATTRS/EDITABLE_FEATURES 且外部格式永不到第三级；免费序列 STEP AP242/STL/BREP→IGES/glTF/OBJ→3MF/DXF（阶段 0 STEP 只写产品化、读仅测试辅助）；商业格式仅经外部持证插件；DWG 不碰。
- **ADR-006**: 平台分层 T1（Ubuntu 22.04/24.04 + Win10/11 x64，CI 三 job pip 直装）/ T2（麒麟 V10 SP1+ / UOS Server 20 / 麒麟 V11 on 鲲鹏·飞腾 aarch64，manylinux_2_31 直装、实机回归阶段 1）/ T3（LoongArch64 技术可行、阶段 1 末 spike go/no-go、申威不纳入）；基线声明 glibc≥2.31，UOS V20 桌面 D（2.28）已知不支持；同时以一个 `## 基线偏离` 段记录偏离 ①（打包主路径 conda→pip+uv，E1/E11 为据，conda 留作离线备选）。

偏离计数核对（测试强制）：`## 基线偏离` 逐字标题在六份 ADR 中共出现 **2 次**，按文件名分别位于 ADR-001（偏离 ②）与 ADR-006（偏离 ①），其余四份为 0；`undo_compensation` 与命令 `version` 字段为协议增强，均不计入偏离。

## 3. Scoped verification (all exit 0)

### 3.1 `uv run ruff check tests/test_adr_docs.py`
```
All checks passed!
exit=0
```

### 3.2 `uv run ruff format --check tests/test_adr_docs.py`
```
1 file already formatted
exit=0
```

### 3.3 `uv run basedpyright tests/test_adr_docs.py`
```
0 errors, 0 warnings, 0 notes
exit=0
```
(strict mode per `pyrightconfig.json`; zero `# type: ignore` / `# pyright: ignore`,
zero `Any` escapes in the file.)

### 3.4 `uv run pytest tests/test_adr_docs.py -q`
```
...............                                                          [100%]
15 passed in 0.14s
exit=0
```

### 3.5 Final no-regression `uv run pytest tests/test_baseline_hashes.py tests/test_spdx.py -q`
```
.....                                                                    [100%]
5 passed in 0.17s
exit=0
```
(Three baseline docs byte-identical — their SHA256 fixtures still match; every
`.py` under tests/ carries the exact SPDX pair, including the new test file.)

## 4. Manual-QA channel — full verbose output

`uv run pytest tests/test_adr_docs.py -v` (real-surface proof):
```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0 -- /media/sima/Data/projects/MyCAD/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /media/sima/Data/projects/MyCAD
configfile: pyproject.toml
plugins: cov-7.1.0
collecting ... collected 15 items

tests/test_adr_docs.py::test_adr_dir_holds_exactly_six_numbered_files PASSED [  6%]
tests/test_adr_docs.py::test_each_adr_has_the_five_section_headers[ADR-001] PASSED [ 13%]
tests/test_adr_docs.py::test_each_adr_has_the_five_section_headers[ADR-002] PASSED [ 20%]
tests/test_adr_docs.py::test_each_adr_has_the_five_section_headers[ADR-003] PASSED [ 26%]
tests/test_adr_docs.py::test_each_adr_has_the_five_section_headers[ADR-004] PASSED [ 33%]
tests/test_adr_docs.py::test_each_adr_has_the_five_section_headers[ADR-005] PASSED [ 40%]
tests/test_adr_docs.py::test_each_adr_has_the_five_section_headers[ADR-006] PASSED [ 46%]
tests/test_adr_docs.py::test_per_adr_required_and_forbidden_tokens[ADR-001] PASSED [ 53%]
tests/test_adr_docs.py::test_per_adr_required_and_forbidden_tokens[ADR-002] PASSED [ 60%]
tests/test_adr_docs.py::test_per_adr_required_and_forbidden_tokens[ADR-003] PASSED [ 66%]
tests/test_adr_docs.py::test_per_adr_required_and_forbidden_tokens[ADR-004] PASSED [ 73%]
tests/test_adr_docs.py::test_per_adr_required_and_forbidden_tokens[ADR-005] PASSED [ 80%]
tests/test_adr_docs.py::test_per_adr_required_and_forbidden_tokens[ADR-006] PASSED [ 86%]
tests/test_adr_docs.py::test_deviation_heading_count_is_two_and_located_by_filename PASSED [ 93%]
tests/test_adr_docs.py::test_no_blocklisted_premature_implementation_phrase PASSED [100%]

============================== 15 passed in 0.13s ==============================
exit=0
```

Coverage mapping to the plan's acceptance criteria: exactly six `ADR-00N-*.md`
files (001–006 each once); five section headers per file (Status field line +
Context/Decision/Consequences/References headings); keyword hits per file —
ADR-001 `重放`/`history_replay`, ADR-002 `timestamp_utc`/`amendments`/
`named_groups` + forbidden `imported_solid` absent (grep-verified: none),
ADR-003 `api_version`/`CommandContribution`/`EntryPoint.module`/
`missing-manifest`/`incompatible-api`, ADR-004 `confirm_execute`/`plan_id`/
`A19`, ADR-005 `DE_Wrapper`/`DUMB_SOLID`/`ASSEMBLY_WITH_ATTRS`/
`EDITABLE_FEATURES`/`DWG`/`priority`/`ProviderConflictError`, ADR-006 `glibc`/
`2.31`/`LoongArch`/`manylinux_2_31`; deviation count == 2 located by FILENAME
in ADR-001 and ADR-006; blocklist of exact premature-implementation phrases
(`阶段 0 实现 MCP server`、`阶段 0 实现 PySide6`、`阶段 0 接入真实 LLM`、
`阶段 0 实现 DWG 写入`) — zero literal substring hits anywhere under docs/adr/.

## 5. Tamper proofs (backup-copy method; no git used)

Backups placed in `/tmp/opencode/t4-tamper/` (outside `docs/adr/` so the
exactly-six-files invariant stays isolated during the GREEN runs).

### Proof 1 — Status section deleted from ADR-004
```
cp docs/adr/ADR-004-mcp-boundary.md /tmp/opencode/t4-tamper/proof1.bak
sed -i '/^Status: Accepted 2026-09-17$/d' docs/adr/ADR-004-mcp-boundary.md
uv run pytest tests/test_adr_docs.py -q
→ FAILED tests/test_adr_docs.py::test_each_adr_has_the_five_section_headers[ADR-004]
  AssertionError: ADR-004: missing Status field line   (1 failed, 14 passed)  RED exit=1
cp /tmp/opencode/t4-tamper/proof1.bak docs/adr/ADR-004-mcp-boundary.md
uv run pytest tests/test_adr_docs.py -q
→ 15 passed in 0.13s                                      GREEN exit=0
rm /tmp/opencode/t4-tamper/proof1.bak
```

### Proof 2 — third `## 基线偏离` heading appended to ADR-003
```
cp docs/adr/ADR-003-...md /tmp/opencode/t4-tamper/proof2.bak
printf '\n## 基线偏离\n\n（篡改测试：多余的第三个偏离标题）\n' >> docs/adr/ADR-003-...md
uv run pytest tests/test_adr_docs.py -q
→ FAILED tests/test_adr_docs.py::test_deviation_heading_count_is_two_and_located_by_filename
  AssertionError: ADR-003-...md: deviation heading is not allowed here (assert 1 == 0)
                                                          (1 failed, 14 passed)  RED exit=1
cp /tmp/opencode/t4-tamper/proof2.bak docs/adr/ADR-003-...md
uv run pytest tests/test_adr_docs.py -q
→ 15 passed in 0.13s                                      GREEN exit=0
rm /tmp/opencode/t4-tamper/proof2.bak
```

### Proof 3 — blocklist phrase appended to ADR-006
```
cp docs/adr/ADR-006-platform-tiering.md /tmp/opencode/t4-tamper/proof3.bak
printf '\n（篡改测试：超前实现表述）阶段 0 实现 MCP server\n' >> docs/adr/ADR-006-platform-tiering.md
uv run pytest tests/test_adr_docs.py -q
→ FAILED tests/test_adr_docs.py::test_no_blocklisted_premature_implementation_phrase
  AssertionError: ADR-006-platform-tiering.md: blocklisted phrase present: '阶段 0 实现 MCP server'
                                                          (1 failed, 14 passed)  RED exit=1
cp /tmp/opencode/t4-tamper/proof3.bak docs/adr/ADR-006-platform-tiering.md
uv run pytest tests/test_adr_docs.py -q
→ 15 passed in 0.11s                                      GREEN exit=0
rm /tmp/opencode/t4-tamper/proof3.bak; rmdir /tmp/opencode/t4-tamper
```

All three tamper classes turn the suite red and each restoration returns it to
green; `.bak` files and the backup directory are removed (verified: `ls
/tmp/opencode/t4-tamper` → No such file or directory).

## 6. Deviations from plan spec

**None of substance.** One non-substantive citation clarification:

1. The plan text (lines 262–263) cites "技术路线 §9 设想的 conda 主路径" for
   deviation ①. In the pinned baseline document the conda-forge main-path
   recommendation actually lives in **技术路线 §4「关键环境与依赖策略」,
   `docs/技术路线.md:92`** (baseline §9 is 开源与第三方, which ADR-005 cites
   accurately for licensing). ADR-006's deviation section therefore cites §4
   with the exact line reference so the baseline claim is verifiable as
   written. The substance of deviation ① (conda main path → pip+uv, E1/E11
   evidence, conda-forge build123d 0.9.1 lag, offline fallback) is unchanged
   from the plan text.

## 7. Adversarial classes

- **misleading_success_output**: probed — keyword/section/deviation/blocklist
  checks are regex assertions over file content, and the three tamper proofs
  each flipped a distinct test red before restoration (no
  always-green assertion possible).
- **malformed_input**: n/a — pure-document task, no runtime input surface.
- **prompt_injection**: n/a — no untrusted content ingested; ADR prose is
  authored from the approved plan and pinned baseline docs only.
- **cancel_resume**: n/a — single uninterrupted session.
- **stale_state**: n/a — no caches; test reads docs/adr/ from disk on every run.
- **flaky_tests**: n/a — no timing, no network, no ordering dependence.
- **hung_commands**: n/a — all commands completed (longest ~1s).
- **repeated_interruptions**: n/a — none occurred.
- **dirty_worktree**: integration-owned — orchestrator commits after
  integration; T4 performed no git operations. Sibling agents (T2/T3) work on
  disjoint paths; no full-suite commands were run to avoid their in-progress
  files.

## 8. What this evidence does NOT cover (later waves)

- T6/T8/T9 implementations that must conform to ADR-001/002/003/005
  (their acceptance tests, not this todo, prove conformance).
- F3 real CI run URL (T1's workflow already pins the three T1 runners).
- Phase-1+ evolution points recorded here as text only (tessellation-backed
  preview, document.import_step, brep snapshot v2, LoongArch spike).
