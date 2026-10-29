# 文档归属与存盘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 为独立草图、工程图和零件实现正确的独立存盘与退出检查，并预留装配文档及依赖图保存契约。

**Architecture:** 用按文档 ID 索引的会话管理任意数量的独立 Document/Bus/内核实例；工作区只选择当前编辑文档。新版本档案记录稳定文件身份、文档种类和可重放来源引用，旧档案隔离读取并显式迁移。保存调度遍历文档依赖图，不依赖三个固定工作区。

**Tech Stack:** Python、PySide6、现有 CommandBus / build123d 适配层、JSON 存档、pytest-qt。

**Spec:** `docs/superpowers/specs/2026-10-28-document-save-ownership-design.md`

## Global Constraints

- 独立草图和工程图 `.my2d`；零件及其内部草图 `.my3d`；`.masm` 仅预留。
- Bus 唯一写入，保留审计六字段和重放；core 禁 CAD/Qt/numpy，ui 禁直接导入 geom。
- v1/v2/v3 校验不放宽，不在工作区切换时修改 `document_type`。
- 用户现有未提交工程图模板工作与上一轮保存修复必须保留，不用 reset 或批量覆盖。
- 相关任务使用路径级四门验证，最终集成全量仅一次；不提交无关修改。
- 用户于 2026-10-29 确认实施；五项任务及最终审查修正已完成，验证细节见 `.omo/evidence/document-save-ownership/acceptance.md`。

## Review Focus

- 激活工作区变化后，异步提交完成仍保存原请求所属文档，不保存后来激活的文档。
- 三个工作区之外存在多个零件，共享引用去重、环检测和源优先保存仍成立。
- 全部关闭中先选择放弃、后取消或写盘失败，之前的内存内容不能已被丢弃。
- 新档身份、另存身份和引用身份不同步改写；同路径、同名异 ID 与移动文件有明确结果。
- 旧混合档内嵌工程图、附着草图和引用修订迁移后重放结果不变，失败不影响当前会话。

## Task 1: 文档身份、类型与存档版本

**Files:**
- Modify: `src/mycad/core/document_kinds.py`, `src/mycad/core/document.py`, `src/mycad/core/persistence.py`
- Create: `src/mycad/core/schema_v4.py`, `tests/core/test_document_archive_v4.py`
- Modify: `src/mycad/app.py`

**Interfaces:**
- 新增 `DocumentKind = Literal["sketch", "drawing", "part"]`；装配身份在未来版本添加，当前文件读取继续拒绝 `.masm`。
- 保留 `DocumentType` 为领域命令门控，sketch/drawing 映射 drawing2d，part 映射 part。
- 新档提供持久 `file_id` 和明确 `document_kind`；运行期 `document_id`/revision 继续作为会话隔离标识。
- `validate_archive_v4(data: object) -> None` 验证身份/种类和既有命令历史结构。
- `fork_app_services(services: AppServices) -> AppServices` 共享注册表/插件/格式表，独立创建几何内核。

- [x] 写失败测试：三种文档往返身份和类型一致；两个文档执行命令互不影响；v1/v2/v3 原结构不变；错种类/后缀拒绝。
- [x] 运行 `uv run pytest tests/core/test_document_archive_v4.py -q`，确认失败原因是新契约尚未实现。
- [x] 实现新版本读取/写入及工厂；复制另存产生新文件 ID，普通保存保留 ID。
- [x] 运行新测试与原 persistence/schema 测试；运行受影响路径 lint、format、basedpyright。

## Task 2: 来源引用与内部实例

**Files:**
- Create: `src/mycad/core/document_references.py`, `src/mycad/builtin_commands/reference_specs.py`
- Modify: `src/mycad/builtin_commands/specs.py`, `src/mycad/core/document_kinds.py`, `src/mycad/geom/kernel.py`, `src/mycad/app.py`
- Create: `tests/core/test_document_references.py`, `tests/geom/test_document_reference_replay.py`

**Interfaces:**
- `DocumentReference` 记录目标 file_id、kind、相对路径、来源对象 ID、采用版本指纹和重放数据。
- 注册 `reference.attach`、`reference.update`、`reference.detach`；参数显式包含采用的数据，执行不做网络/磁盘读取。
- 工程图可消费来源模型或草图；模型仅将独立二维来源导入为内部草图实例。
- 关联实例只读，detach 后作为内部草图编辑；更新引用是显式命令并支持 undo/redo。
- 依赖解析拒绝错 ID、错种类及循环；路径定位与引用身份校验分离。

- [x] 写失败测试：源二维图→模型→工程图隔离重放；来源文件缺失仍可显示采用版本；更新可撤销；解除关联后不再跟随源更新。
- [x] 写关联实例编辑拒绝、同名异 ID 拒绝及附着内部草图重放测试。
- [x] 运行 scoped 测试确认失败；实现纯 DTO 校验、命令规格和后端消费，所有修改通过 Bus。
- [x] 跑新 tests/core、tests/geom 测试与 `tests/test_layering.py`，完成路径级静态检查。

## Task 3: 任意数量文档的会话与工作区绑定

**Files:**
- Create: `src/mycad/ui/document_session.py`, `tests/ui/test_document_session.py`
- Modify: `src/mycad/ui/main_window.py`, `src/mycad/ui/entry.py`, `src/mycad/ui/workspace_tabs.py`
- Modify: `src/mycad/ui/viewport.py`, `src/mycad/ui/cli_tab.py`, `src/mycad/ui/drawing_workbench.py`, `src/mycad/ui/new_document_dialog.py`

**Interfaces:**
- `SessionDocument` 持有独立 services、LoadedDocument、kind、path 和该文档的编辑/视图状态。
- `DocumentSession` 按运行期文档 ID 管理条目，提供 `add`、`activate`、`remove`、`documents`；不硬编码最多三个。
- `MainWindow` 激活文档时同步重绑 viewport、CLI、计划、属性、工程图来源和标题；每个回调捕获原文档身份。
- 独立二维入口与模型内部草图入口区分。工作区切换保持草稿、相机和历史；新建空白占位不触发关闭保存提示。
- 工程图选择来源文档/对象，独立草图提供显式“用于建模”；两个操作走 Task 2 引用命令。

- [x] 写失败测试：三个独立文档同时存在、两个零件共存、切换后草稿/历史保留、编辑器身份正确。
- [x] 写异步提交过程中激活另一文档的测试，断言提交和保存只改变原文档。
- [x] 实现会话和公共重绑入口，禁止通过 UI 直接替换后端私有属性。
- [x] 运行新会话测试、workspace/CLI/sketch/drawing 相关回归，检查分层和类型。

## Task 4: 保存调度、另存和多文档关闭

**Files:**
- Create: `src/mycad/core/document_dependencies.py`, `src/mycad/ui/document_save.py`, `src/mycad/ui/unsaved_documents_dialog.py`
- Create: `tests/core/test_document_dependencies.py`, `tests/ui/test_document_save_session.py`
- Modify: `src/mycad/ui/main_window.py`, `tests/ui/test_document_lifecycle.py`

**Interfaces:**
- `save_order(nodes: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]` 返回来源在前的稳定拓扑序，循环显式报错。
- 保存请求绑定 `SessionDocument`，成功才更新其路径和保存状态；不使用运行时激活页决定完成回调的目标。
- “全部保存”先收集目标路径/覆盖决策，再按依赖保存；返回每文档 success/cancel/failure/pending 结果。
- 关闭对话框收集每文档 save/discard/cancel 决策；所有处理成功后才真正销毁文档和关闭窗口。
- 同路径检查使用平台规范化路径，避免同一文件被不同文档覆盖；保存后缀与种类一致。

- [x] 写失败测试：三个未命名文件的默认名和过滤器、保存一份其余仍脏、模型内部草图只对应模型一项。
- [x] 写全部保存路径冲突、取消、第二文件写入失败和源优先保存测试。
- [x] 写关闭中“先放弃后取消/失败”保留内容、全部成功才退出的测试。
- [x] 用抽象图测试多个零件、共享子装配、总装配、工程图顺序；不添加实际装配格式读写。
- [x] 实现保存控制器、全部保存菜单和关闭清单；沿用原子单文件写入及草图提交失败保护。
- [x] 跑相关生命周期/新保存测试及路径级静态检查。

## Task 5: 旧档迁移与最终验收

**Files:**
- Create: `src/mycad/core/document_migration.py`, `tests/core/test_document_migration.py`
- Modify: `src/mycad/app.py`, `README.md`, `docs/工程图操作指南.md`
- Create: `docs/adr/ADR-013-document-ownership-and-save-session.md`
- Append: `.omo/start-work/ledger.jsonl`

**Interfaces:**
- 迁移函数对旧档产生候选文档集合和引用关系，调用者隔离重放成功后才加入会话。
- 原命令审计字段和原文件保留；旧内部草图随零件，工程图分离为引用该零件的新文档。
- 不能确定独立草图意图的旧内容保守保留，并通过显式分离操作处理。

- [x] 写失败测试：旧 v1/v2/v3、含附着草图/工程图的混合档、迁移失败回滚；原文件字节不变。
- [x] 实现迁移并完成二维来源→模型→工程图的保存/关闭/重开验收。
- [x] 更新 README、用户指南和 ADR，记录 `.masm` 仍未实现，另存与未来打包的区别。
- [x] 最终运行一次全量四门；对既有未提交工作导致的基线失败分别报告，不混入本次修复。
- [x] 独立审查修改和保存失败路径，记录验证、缺陷及清理结果；只交付本任务文件变更。
