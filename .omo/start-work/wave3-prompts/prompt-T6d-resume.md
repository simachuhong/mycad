# T6d-resume：持久化测试+集成测试片（D9-D14 续作）

你是在续作一个被配额墙击杀的 T6d 任务实例。**第一动作**：
`cat .omo/start-work/wave3-prompts/prompt-T6d.md` —— 它是本片的完整规格权威
（§0 反停摆纪律/§2 上游 API/§4 钉死设计/§4.5 测试矩阵/§6 终验命令/§7 DoneClaim）。

## 状态声明（磁盘核实，编排方 2026-10-06 17:40 验收）

- **已完成并采信（只读禁改）**：D0-D8 全部——
  - `src/mycad/core/exceptions.py`（ArchiveVersionError += found: str = "" / supported: str | int = ""）
  - `src/mycad/core/migrations/__init__.py`（60L：Migration frozen + register + migrate，v1 恒等）
  - `src/mycad/core/schema_v1.py`（226L：ARCHIVE_FORMAT="mycad.document"/ARCHIVE_VERSION=1/validate_archive/_scan_nulls/selector_from_json/_face_from_json/_edge_from_json）
  - `src/mycad/core/persistence.py`（264L：LoadedDocument frozen + save_document(document, path) 原子写+document_saving/saved 信号 + open_document(path, *, registry, kernel, handlers) 全流水线 + _require_command 预检 + _build_document）
  - `src/mycad/core/__init__.py`（64L 聚合导出，import 链已验证无环）
  - `tests/test_core_isolation.py`（44L subprocess 模式）
  - 编排方已跑 `pytest tests/core/ tests/test_exceptions.py tests/test_core_isolation.py tests/test_layering.py` → **139 passed 全绿**
- **原提示词 §5 清单里的 "DONE D9"–"DONE D14" 标记与磁盘矛盾，全部忽略**——那是死亡实例的失真状态。磁盘事实：`tests/core/test_persistence.py` 与 `tests/core/test_core_integration.py` **不存在**，evidence §T6d **未写**。
- 你的全部工作 = 原清单 **D9→D14**（仅此六步）。

## 已交付 API 速查（写测试直接用，勿臆造；存疑时 cat 源文件核实）

- `save_document(document: Document, path: Path) -> None`：原子写（NamedTemporaryFile+os.replace）；写前 emit `document_saving` payload={"path": str(path)}，写后 `document_saved`；JSON ensure_ascii=False indent=2；父目录不存在 OSError 透传。
- `open_document(path, *, registry, kernel, handlers) -> LoadedDocument`：read_text→json.loads（JSONDecodeError→ValidationError 带 line/col）→顶层非对象→ValidationError→format 检查（ArchiveVersionError found=实际串或"missing"/supported="mycad.document"）→version 检查（found=str(version) 如 "99"/supported=1）→migrate 恒等→validate_archive→逐命令 _require_command（缺 handler→UnknownCommandError 含 ordinal 与 id）→_build_document→CommandBus→一次 _rebuild→LoadedDocument(document=..., bus=...)。
- `schema_v1.validate_archive(data) / selector_from_json(data, pointer)`；migrations `register(migration) / migrate(data)`（无链 ValueError 文案含版本数字）。
- 夹具形态：`FakeKernel/FakeHandler/EchoHandler` 同 test_bus.py（cat tests/core/test_bus.py 头部参考）；Document/CommandBus 装配同 test_document.py/test_bus.py 既有模式。
- specs 形态参考 tests/geom 夹具（box {"size_x":10.0,"size_y":20.0,"size_z":30.0}）；demo_registry() 在 mycad.commands.demo。

## Resume 清单（从 R1 顺序机械执行；每步完成才下一步）

- R1：cat §2 参考文件中你尚不熟悉的（test_bus.py 夹具、tests/geom 夹具、document.py/bus.py 内部 API）+ §4.5 测试矩阵精读。禁写任何文件。
- R2：cat > tests/core/test_persistence.py 第一批（文件头+migrations 类+恒等，≤80 行）→ `uv run pytest tests/core/test_persistence.py -q` 绿。
- R3：cat >> 第二批（异常矩阵全例，≤120 行）→ 绿。
- R4：cat >> 第三批（往返矩阵全例，≤130 行）→ 绿。
- R5：cat > tests/core/test_core_integration.py 块一（自建 spec 装配+①execute/undo/redo 体积+②edit_and_replay，≤110 行）→ 绿。
- R6：前置实验选定几何失败命令（见 §4.5 ④：优先 modify.fillet 超大半径 on 10mm box，`uv run python -c` 实证抛 GeometryBuildError；不抛则换 boolean_cut 空工具体，选型记录留待 evidence）→ cat >> 块二（③QA happy path ④批回滚两场景 ⑤性能门，≤150 行）→ 绿。
- R7（终验=原 D14）：§6 全部命令跑绿（pytest 七文件/basedpyright 八文件点名/ruff check+format 同清单）→ `cat >> .omo/evidence/task-6-phase0-mvp.md` 追加 §T6d 段（D13 失败命令实验选型+QA 输出摘录+性能实测值+偏离记录）→ 回合输出 DoneClaim（§7 格式，deliverables=你创建的文件+evidence）。

## 反停摆五纪律（违反=任务失败）

1. 禁写任何清单/提示词文件；禁改 src/mycad/core/ 全部现存文件、exceptions.py、test_core_isolation.py、既有测试。
2. 单文件单批写入 ≤150 行（cat > 首批 / cat >> 追加）；每批后立即跑 scoped pytest。
3. 每回合恰好一个小动作（写一批/跑一次验证）；禁长篇推理，直接执行。
4. 遇 BLOCKED（规格冲突/上游缺失）立即停止并输出 BLOCKED 说明，勿自行发明。
5. 全程禁 git 操作（add/commit/branch 等）。
