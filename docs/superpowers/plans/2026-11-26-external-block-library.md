# 外部二维块库 Implementation Plan

> **For agentic workers:** 在设计评审通过后使用 superpowers:executing-plans 顺序实施；本文件是待评审计划，不是开发已完成记录。按复选框逐项记录结果。

**Goal:** 将当前图纸中的块保存为本地库文件，并通过本地或共享目录，在其他二维图纸中浏览、预览、导入和插入，保存后的图纸独立于块库。

**Architecture:** 单文件单块的 `.myblock` v1 JSON，目录为资产源。不可变资源及导入规划放 core，文件编解码放 formats，磁盘存储放 libraries；UI 经应用服务和现有集合暂存会话写入文档。首次插入复用持久复合命令。

**Tech Stack:** 现有 Python、PySide6、ezdxf、stdlib JSON/hashlib/uuid/pathlib；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-11-26-external-block-library-design.md`（必须先读，仍待评审）。

## Global Constraints

- 仅独立二维文档；块内容限既有几何与文字；禁止嵌套、属性、动态块及约束。
- 用户确认本地库＋共享目录；共享只读、库图纸互不自动同步属于建议，需随设计确认。
- 原生资产格式 v1、单位 mm；文档命令最低 v8，旧文档走显式升级候选，不改 `.my2d` 顶层。
- 复用当前工作区 `codex/phase2-foundation`；不 stash/reset，不从旧 HEAD 重建工作树，不 `git add .`，本规划不提交用户已有改动。
- 文档写入仅经 Bus/候选；库文件操作不进入文档历史。预览与提交身份相同，历史重放不得读外部库。
- 先红测后实现，仅执行新用例与直接受影响项；`uv run --no-sync`。已通过且未受影响的不重跑，不预排全量测试。
- Ruff、format、basedpyright 只检查本任务修改路径；新增分层边界时运行 `tests/test_layering.py` 相关项一次，后续无边界变化不重复。
- 每项立即记录实际命令、结果、文件、技术决定和下一入口到 `.omo/start-work/external-block-library-progress.md`；人工结果单独记录。

## Review Focus

- 同库条目已被 BEDIT 修改后再插入：不能覆盖旧实例，也不能因名称相同错误复用（L2）。
- 样式/图层同名不同属性之后重复插入：不能无限生成副本资源（L2）。
- 源草稿未保存，先确认约束再修剪，然后导出：必须从正确合并视图取定义且不暗中提交草稿（L3/L4）。
- 目标图纸在预览期间改变或切换：拒绝过期候选，不把资源写到另一个文档（L3）。
- 共享文件扫描/读取期间被替换，且本地更新同时发生：不缓存半文件，不误报保存成功（L1/L4）。

## 接口与类型约定

以下是拟新增接口，名称/字段在实施时以本计划为基线，不把私有 UI 回调用作公共协议。

- `BlockAsset(asset_id, name, description, tags, definition, text_styles, layers, content_sha256)`：frozen 值，集合强制 tuple；单位 mm、格式版本在 codec 固定为 1。
- `AssetMetadata(name: str, description: str, tags: tuple[str, ...])`。
- `AssetIssue(code: str, message: str, field_path: str | None)`：只读诊断。
- `BlockLibraryOrigin(definition_id: str, asset_id: str, content_sha256: str)`：定义到库资产版本的不可变来源记录，独立于 BlockDefinition v1 参数。
- `BlockPlacement(insertion_mm: Point2D, rotation_deg: float, scale: float, layer_name: str)`。
- `PreparedBlockImport(operation: ReplayAppend | None, definition_id: str, instance_id: str | None, issues: tuple[AssetIssue, ...])`：仅导入已存在的等价定义时 operation=None，无空 batch；UI 不把该情况称为新增。
- `LibraryRoot(root_id: str, path: Path, read_only: bool)`；共享源必须 read_only=True。
- `LibraryEntry(root_id: str, relative_path: str, file_digest: str, asset: BlockAsset)`；`LibraryScan(entries, issues)`；`LibraryWriteReceipt(path, file_digest, previous_version_path)`。这些 Path 类型只属于存储接口，不进入文档命令。

### L0：资产值、依赖闭包与原生格式

**Files:** 新建 `src/mycad/core/block_library.py`、`src/mycad/formats/block_asset.py`；测试 `tests/core/test_block_library.py`、`tests/formats/test_block_asset.py`。

**Interfaces:**
- `capture_block_asset(snapshot: DrawingCollectionSnapshot, definition_id: str, metadata: AssetMetadata, *, asset_id: str) -> BlockAsset`。
- `block_asset_digest(asset: BlockAsset) -> str`；内容字段与设计稿一致。
- `encode_block_asset(asset: BlockAsset) -> bytes` / `decode_block_asset(data: bytes) -> BlockAsset`。

- [ ] 写失败用例 `test_capture_unplaced_and_text_only_definition`：不需要实例；样式/非 0 层依赖完整；未使用资源不泄漏；源 snapshot 不变。
- [ ] 写 `test_asset_roundtrip_and_invalid_input` 参数化：几何/文字/曲线点身份一致、摘要稳定；未知版本、坏摘要、缺依赖、重复 JSON 键/ID、非有限数、过大文件拒绝。
- [ ] 运行上述两个新增测试文件，确认失败原因来自缺少行为，然后实现接口。落实设计稿的 16 MiB、50,000 对象、500,000 曲线点、4 MiB 文字、32 层嵌套限制并加入边界用例，不能留下无限嵌套解析。
- [ ] 运行 `uv run --no-sync pytest tests/core/test_block_library.py tests/formats/test_block_asset.py -q`，要求全部通过；在记录中列出实际断言覆盖和已确定的限制常量。

**出口：** 一份块文件可完全独立解码，定义和依赖齐全，不依赖内核或 GUI。

### L1：本地库存储、共享目录读取与缓存失效

**Files:** 新建 `src/mycad/libraries/__init__.py`、`src/mycad/libraries/block_store.py`；测试 `tests/libraries/test_block_store.py`。

**Consumes:** L0 编解码和 BlockAsset。

**Produces:** `BlockLibraryStore`，构造时传入 roots/cache_dir；`scan(root_id) -> LibraryScan`、`read(entry) -> BlockAsset`、`save(root_id, category, asset, *, expected_digest: str | None) -> LibraryWriteReceipt`、`trash(entry) -> LibraryWriteReceipt`、`restore(receipt) -> LibraryWriteReceipt`。None 表示只允许创建新条目，不表示无条件覆盖。回执记录恢复前预期当前摘要（回收则预期不存在），恢复也取得锁并核对摘要/根目录只读状态，不满足时冲突退出。

- [ ] 写 `test_local_save_failure_keeps_original_and_cleans_temp`：原子替换失败/无权限/摘要过期均不破坏原文件，返回可读错误。
- [ ] 写 `test_shared_readonly_offline_and_bad_entry`、`test_concurrent_update_and_replaced_read`：共享写入拒绝；离线不当空库；坏条目不阻断正常条目；进程间竞争至少一个冲突；读取换版无半文件。
- [ ] 写 `test_trash_restore_and_index_rebuild`：回收可恢复，更新保留旧版；V1→V2 后被另一个进程改成 V3，恢复 V1 不得覆盖 V3；回收恢复路径被占用时拒绝；目录配置移除不删文件；丢缓存后重建；符号链接循环终止。
- [ ] 红测后实现锁、expected digest、临时文件清理、缓存指纹和不跟随目录链接循环的扫描；UI 调度器负责后台运行，存储类本身不引 Qt。
- [ ] 运行 `uv run --no-sync pytest tests/libraries/test_block_store.py -q`，只补本模块边界检查。

**出口：** 本地可写、共享只读，失败不丢块文件；索引不是唯一真相源。

### L2：导入规划、稳定复用与资源冲突

**Files:** 新建 `src/mycad/core/block_library_import.py`、`src/mycad/core/drawing_resource_merge.py`；接入 `core/drawing_collection_state.py`、`core/kernel_protocol.py`、`core/document_kinds.py`、`builtin_commands/drawing_block_specs.py`、`geom/kernel.py`、`app.py`；必要小改 `formats/dxf_collection_import.py`；测试 `tests/core/test_block_library_import.py`、`tests/app/test_block_library_import.py`。

**Consumes:** BlockAsset、DrawingCollectionSnapshot、BlockPlacement。

**Produces:** `prepare_block_library_import(asset, target, *, placement: BlockPlacement | None) -> PreparedBlockImport`。使用设计稿来源记录＋内容核对算法及现有 ReplayAppend；返回具体资源决策提示，不执行写入。

- [ ] 先写 `test_library_origin_command_lifecycle`：绑定命令的 schema/固定版本/二维门控/batch 白名单正确；无定义不能绑定、不能重绑；reset、候选复制/失败回滚、安装、普通和优化重放保留来源，删除定义清理。红测后注册 `drawing.block_library.bind@1`（v8），来源 tuple 加入状态与只读应用快照，保留旧构造默认空值。
- [ ] 用真实 Bus 写 `test_repeat_library_insert_after_reopen_reuses_definition`：首次插入、再次插入、存档重开再次插入；始终一份定义，实例 ID 不同。含文字、非 0 层和曲线点。
- [ ] 写 `test_library_import_after_bedit_keeps_old_instances`、`test_conflicting_resources_repeat_without_growth`、`test_library_import_rejects_locked_layer_without_mutation`；验证同名异内容、同身份异内容/已改样式、资源数量稳定、锁层拒绝。
- [ ] 写 `test_reuse_after_deleting_earlier_import_and_reopen`：原版导入→BEDIT→再导入原版→删除较早定义及实例→保存重开→插入，复用仍存在的原版；不同 asset_id 相同内容不复用。
- [ ] 红测后实现依赖协调、来源发现、去身份的实际内容核对和冻结新身份；优先复用公开纯函数，必要抽取小段，保留旧 clipboard/DXF 策略默认值。
- [ ] 写并通过 `test_definition_only_import_and_empty_noop`：无实例导入后可正常 INSERT；重复仅导入不新增历史；只含文字的定义也成立。
- [ ] 写并通过 `test_import_batch_failure_and_reopened_undo`：资源＋定义＋来源绑定＋首个实例一并撤销/回滚；断开源路径仍能重放；随后的普通 sketch revise/优化重建不丢状态。
- [ ] 运行 `uv run --no-sync pytest tests/core/test_block_library_import.py tests/app/test_block_library_import.py -q`；若抽取了样式/图层协调，仅附加实际受影响的既有剪贴板与 DXF 冲突用例，不跑全模块全集。

**出口：** 无 GUI 的跨文件使用闭环；重复插入和重开撤销成立后才能开始 L3。

### L3：草稿与应用服务接入

**Files:** 新建 `src/mycad/ui/block_library_controller.py`；小改 `src/mycad/app.py`、`ui/drawing_collection_session.py`（仅必要时）、`ui/main_window.py`；测试 `tests/ui/test_block_library_session.py`。

**Consumes:** L0 capture、L1 store、L2 prepare，以及现有 `stage_collection_operation`。

**Produces:** `BlockLibraryController`，接收只读合并视图、当前文档/会话 token、导入暂存回调及 store；`save_definition(definition_id, metadata, destination)`、`prepare_import(entry, placement)`、`confirm_import(preview)`、`cancel_import()`。preview 保留文件摘要、冻结资产、目标 revision/checkpoint、PreparedBlockImport；变换参数更新不重新随机分配已准备对象身份。

- [ ] 写 `test_export_trimmed_constrained_draft_without_commit`：未完成草稿做确认约束、尺寸删除、修剪/圆角、保留源创建块；导出不提交草稿；取消草稿后块文件仍可读。
- [ ] 写 `test_library_insert_draft_undo_redo_cancel`：既有 A＋草稿 B＋库实例，逐步 undo/redo 与取消恢复；源文件保留。
- [ ] 写 `test_library_preview_document_switch_and_revision_change`、`test_library_placement_cancel_leaves_no_resources`：过期候选拒绝，切文档无串写，取消不留图层/样式/定义。
- [ ] 红测后接入集合会话，首次确认一次 batch；目标 v8 以下复用已有升级入口，不在控制器私改版本。
- [ ] 运行 `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_block_library_session.py -q`；仅新增必要的一条现有 BLOCK 草稿相关回归。

**出口：** 保存到库与图纸事务边界清楚，未保存草稿可正常使用。

### L4：块库 UI 与真实操作入口

**Files:** 新建 `ui/block_library_dialog.py`、`ui/block_library_preview.py`；小改 `ui/drawing_block_dialogs.py`、`ui/main_window.py`、`ui/preferences.py` 和现有二维命令分发所在模块；测试 `tests/ui/test_block_library_dialog.py`、`tests/ui/test_block_library_workflow.py`。

**Consumes:** Controller、只读 LibraryEntry 和已校验 BlockAsset。预览复用 `expand_block`/既有文字布局，不将派生图元加入主画布可编辑集合。

- [ ] 写真实按钮及命令路径测试：块管理保存无实例定义 → 库列表立即出现 → 新图 INSERT 外部入口 → 画布点击/Enter/右键确认 → 块管理看到定义；Esc 退出。
- [ ] 写 `test_library_empty_error_and_missing_font_feedback`：空库引导、坏条目、离线目录、字体替代信息可见；保存失败保留字段。
- [ ] 写 `test_library_scan_generation_and_preview_refresh`：后台旧结果不覆盖新目录/搜索结果，条目文件更新使缩略图失效，关闭窗口后任务不更新已销毁控件。
- [ ] 红测后实现中文可调整窗口、来源分类/搜索/预览/详情，工具栏入口、BLOCKLIB/WBLOCK 工作流和 INSERT 来源切换；新增命令重复逻辑遵循已有空闲右键路径。
- [ ] 运行 `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_block_library_dialog.py tests/ui/test_block_library_workflow.py -q`。桌面启动只读/可写根分别走一遍，记录实际平台；Wayland/XCB 的浏览/放置分别验收，不把离屏测试当桌面结果。

**出口：** 用户可从正常窗口/按钮/命令完成跨文件操作，无需剪贴板中转。

### L5：DXF 入库与交换

**Files:** 新建 `formats/block_library_dxf.py`；小改 `formats/providers/dxf_provider.py`（若需提取定义目录接口）、`ui/block_library_dialog.py`；测试 `tests/formats/test_block_library_dxf.py`、`tests/ui/test_block_library_dxf_import.py`。

**Produces:** `read_dxf_block_assets(path, *, unit_override: str | None) -> tuple[tuple[BlockAsset, ...], tuple[AssetIssue, ...]]`；`write_block_asset_dxf(asset, path) -> DxfExchangeReport`。资产选择与持久保存仍经 L1，不由 DXF reader 自动写库。模型空间选项单独准备一个候选，需明确 name/base_mm。

- [ ] 写未引用命名块、纯块、纯文字块、非零基点、英寸转 mm、单位未知、专用 INSERT 排除及嵌套整块拒绝用例。
- [ ] 写实际 DXF 输出字节导回测试：定义＋展示实例、样式、图层、基点和文字尺寸一致；存在损失时预览明确报告。
- [ ] 红测后复用既有 provider；不得为本任务复制一个 DXF 全文件解析器，不增加 DWG/商业转换依赖。
- [ ] 运行 `uv run --no-sync pytest tests/formats/test_block_library_dxf.py -q` 与 `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_block_library_dxf_import.py -q`；仅 provider 接口改变时增加直接受影响的既有专用 INSERT 识别用例。

**出口：** 实际 DXF 可选择入库并用于新图；预览与最终文件一致。

### L6：交接、样例与人工验收

**Files:** 新建 `docs/design/2026-11-26-external-block-library-manual-check.md`、`docs/examples/block-library/` 的可重建样例；更新 README 功能说明及本工作包进度记录。

- [ ] 提供几何＋中文文字＋非 0 层、纯文字、无实例定义、同名不同内容、坏文件及不支持 DXF 样例，注明预期结果。
- [ ] 人工按“图 A 建块（未完成草稿）→ 入库 → 取消 A → 图 B 插入两次 → 保存重开 → 再次插入 → BEDIT → 再次从库插入 → 逐步撤销/重做 → 断开库重开”验收。
- [ ] 分别记录本地、共享只读、离线、缺字体、仅导入定义、重命名/回收/恢复、DXF 损失反馈，及平台/版本/实际结果。
- [ ] 收拢已有分项自动验证记录，不为交付重复已通过测试；AutoCAD 2023/2025 外部交换人工结果待实际运行，不代填通过，公差人工状态保持独立。

**最终出口：** 本地和共享目录中的块能从 UI 用于其他文件，文档独立保存且事务正确；剩余限制可见。任一领域单测或文件列表完成都不代表此出口完成。

## 交接与实施顺序

严格 `L0 → L1 → L2 → L3 → L4 → L5 → L6`，不并行改主窗口、候选流程或 DXF provider。L0–L4 构成原生跨文件闭环；L5 完成交换；L6 交付人工验收资料。最大风险为 L2 身份/资源复用与 L3 草稿事务，先取得出口证据再扩展界面。

本轮未执行上述任何实现/测试步骤。开发起点为设计评审通过后的 L0。
