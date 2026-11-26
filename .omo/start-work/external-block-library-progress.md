# 外部二维块库进度

## 2026-11-26：技术评估与规划

- 用户要求：外部块库必须实现；本轮先技术评估与规划。用户已确认“本地块库＋共享目录”。
- 当前分支：`codex/phase2-foundation`；继续使用现有工作区，不改动既有未提交业务代码。
- 已核对：块领域类型、块管理/创建/插入、集合剪贴板、文字样式协调、集合暂存、应用合并快照、DXF 定义/实例与未引用块路径、字体资源及原子文件写入现状。
- 产物：`docs/superpowers/specs/2026-11-26-external-block-library-design.md`、`docs/superpowers/plans/2026-11-26-external-block-library.md`。
- 推荐方案：单文件单块 `.myblock` v1＋目录库；目标图纸内保存实际定义和资源，断开库仍可编辑/重放。共享目录首期只读是待评审建议，不冒充用户已确认。
- 主要技术风险：资源冲突后重复插入的稳定复用、BEDIT 修改后的身份分叉、草稿入库与图纸撤销边界、候选过期、文件替换与只读共享目录离线。
- 实施阶段：L0 资产格式 → L1 存储 → L2 导入事务 → L3 草稿 → L4 UI → L5 DXF → L6 人工交接。全部尚未开始。
- 验证：本轮仅阅读/检索及文档检查，未运行 pytest、Ruff、basedpyright 或 GUI；既有测试结果不当作新功能通过证据。
- 下一入口：完成方案评审后从 L0 开始；未经新指令不在本规划轮次启动开发。

- 方案独立审读发现并修正：连续派生候选 ID 在删除较早定义后会漏认其余候选；改为 `drawing.block_library.bind@1` 记录可重放来源＋实际内容核对，完整纳入生命周期/优化重放，仍不改存档顶层。补充删除旧候选后重开再插入测试。
- 同时补齐本地恢复并发契约：恢复必须匹配回执记录的当前摘要，不能覆盖后续 V3；回收恢复路径占用则拒绝，共享只读也适用于恢复。独立审读未执行测试，未修改业务代码。

## 2026-11-26：L0 资产与原生编码（进行中）

- 新增 `src/mycad/core/block_library.py` 与 `src/mycad/formats/block_asset.py`，定义不可变块资产、依赖捕获、规范摘要、严格 JSON 格式与文件大小/嵌套/成员/曲线点/文字上限。字体路径保留文件名；文字样式和非 0 层只带所需项。
- `uv run --no-sync pytest tests/core/test_block_library.py tests/formats/test_block_asset.py -q --tb=short` 首次失败（缺失新模块），实现后修正测试 fixture 的标注样式初始化，3 passed。新增缺依赖、重复身份、字符串括号和转义测试，定向 2 passed；新增成员、曲线点与 UTF-8 文字上限定向 2 passed（缩小常量验证边界分支）。
- 四个修改路径 Ruff、format、basedpyright 通过；后续新增核心测试路径单独检查通过。分层检查运行中，需收集最终结果。
- 尚需审查/完善完整边界以及 L1 后续；功能尚未接入库目录、事务和界面，不能宣称外部块库可用。
- L0 分层检查：`uv run --no-sync pytest tests/test_layering.py -q --tb=short` → 6 passed（75.75 s）。

## 2026-11-26：L1 库目录存储

- 新增 `src/mycad/libraries/block_store.py` 和包入口：扫描本地/共享目录并逐条反馈异常、读取时校验扫描摘要、本地进程间锁、同目录临时文件＋fsync＋原子替换、按摘要控制更新及恢复、版本备份、回收恢复、阻止目录穿越和符号链接。
- 本地同分类新条目重名确定性追加副本后缀，更新重名拒绝；共享源为只读；缓存目录参数保留，当前扫描不持久化索引，后续 UI 后台扫描再接入。
- 测试先因缺少模块失败，初版通过 3 项；新增 4 项暴露重名和内部目录问题，修复后通过；新增多进程竞争与符号链接 2 passed；新增重命名冲突和链接报告先失败后通过。直接受影响完整存储测试 `uv run --no-sync pytest tests/libraries/test_block_store.py -q --tb=short` → 10 passed。
- `uv run --no-sync ruff check src/mycad/libraries tests/libraries/test_block_store.py`、`ruff format --check` 及 `basedpyright` 对同路径通过。格式和类型修正后已复查；此前首轮 basedpyright 的注解问题已修复。
- 下一入口：L2 来源绑定命令、内核生命周期、导入资源协调及真实 Bus 重开撤销；UI 与 DXF 均尚未接入。

## 2026-11-26：L2 来源绑定（进行中）

- 新增 `BlockLibraryOrigin` 和内部 `drawing.block_library.bind@1`，接入独立二维门控、复合命令白名单、内核只读状态、reset/候选安装/优化重建/删除清理及应用快照。命令历史可重放，不改存档顶层。尚未实现资产导入与重复复用规划。
- `tests/app/test_block_library_import.py::test_library_origin_command_lifecycle` 首次因未知命令失败，接入后 1 passed；覆盖无定义拒绝、复合命令、重绑定拒绝、保存重开及撤销/重做、删除清理。
- `test_origin_survives_optimized_rebuild_and_failed_batch`、`test_origin_rejected_outside_independent_drawing` → 2 passed；覆盖失败回滚、草图修订后状态、非独立二维拒绝。此项尚需更严格地验证优化路径实际被调用、绑定状态版本/无效 ID 和候选生命周期，不能把 L2 标成完成。
- 修改路径 Ruff 通过；basedpyright 首轮报告 `drawing_collection_state.py` 2 处不必要的 isinstance 类型错误，修复后该文件定向 0 errors；其余路径首轮未报错。新增测试后需检查测试文件。下一入口：补强绑定生命周期与编写导入规划的失败测试。
- L2 导入规划首轮：新增 `core/block_library_import.py`，冻结资源/定义/来源/实例为一个 batch，按来源与成员实际内容复用；按属性合并样式与图层、冲突后缀、拒绝锁层。
- `test_repeat_library_insert_after_reopen_reuses_definition` 红测缺少模块，实施后 1 passed；`test_import_after_bedit_delete_and_reopen_reuses_remaining_copy`、`test_definition_only_import_is_noop_on_repeat` 2 passed；样式/图层冲突重复导入不增长 1 passed；`test_import_batch_undo_reopen_and_locked_target` 1 passed。导入规划及测试路径 Ruff、format、basedpyright 通过。
- L2 仍进行中：需检查曲线点身份、不同资产身份、失败候选版本/优化路径探针及对 0 层/源层锁状态的边界，随后接草稿和 UI。所有库操作目前尚不可从 UI 使用。
- L2 补证：`test_curve_identity_and_distinct_asset_id_import` 1 passed，曲线/点 ID 重分配、同资产复用、不同资产不合并；`test_origin_survives_optimized_rebuild_and_failed_batch` 加探针后 1 passed，确认确实调用优化重建并保留来源。

## 2026-11-26：L3 草稿控制器（进行中）

- 新增 `ui/block_library_controller.py`：从合并快照另存定义、冻结文件与图纸候选、检查 checkpoint/快照后一次暂存、取消预览。尚未接入真实画布/主窗口；不宣称 UI 交互已实现。
- `QT_QPA_PLATFORM=offscreen uv run --no-sync pytest tests/ui/test_block_library_session.py -q --tb=short`：首轮缺模块失败，实现后 2 passed；真实集合会话覆盖草稿另存、导入、撤销/重做、取消草稿后库文件仍在、预览取消和草稿变化拒绝。控制器与测试路径 Ruff、格式及 basedpyright 通过。
- 下一入口：未完成草稿约束/修剪真实窗口导出与文档切换场景；随后接块管理、插入及库窗口。用户真实桌面与 AutoCAD 验收尚未执行。
- 草稿控制器补充：放置预览重新定位时保留首次分配的定义、成员与实例 ID，旧预览不能再提交。`test_reposition_preview_keeps_frozen_ids_and_stages_final_point` 首轮因缺方法失败，实现后 1 passed；控制器与测试路径 Ruff、格式及 basedpyright 通过。真实画布实时预览尚未接入。
- L3 预览跨文档会话测试：`test_preview_rejects_document_switch_without_writes` → 1 passed，切换 session identity 后拒绝暂存且无文档写入。

## 2026-11-26：L4 浏览与保存对话框（进行中）

- 新增 `ui/block_library_dialog.py` 与 `ui/block_library_preview.py`：后台扫描、搜索、列表、使用既有画布渲染几何/文字的只读预览、损坏/离线反馈、定义导入/插入选择；新增保存对话框保留失败输入并显示保存位置。
- `tests/ui/test_block_library_dialog.py` 浏览/预览和共享目录离线 2 passed；保存对话框失败保持输入、再次成功 1 passed。各项首先因模块/类缺失失败，再实现通过。UI 路径 Ruff、format、basedpyright 通过（初次类型错误已修复）。
- `BlockManagerDialog` 新增可选“保存到块库”回调入口；`test_manager_saves_unplaced_definition` 先失败后 1 passed；相关路径 lint/type 通过。该入口尚未连接主窗口和真实存储，块库按钮/命令、目录配置、实际放置与共享目录管理尚未完成。
- 下一入口：主窗口接入保存/读取及工具栏入口，补齐共享目录配置与异步扫描生命周期、真实画布放置；之后执行 DXF 及交接。
- 主窗口接入了本地块管理“保存到块库”、块与组工具栏“块库”按钮、浏览后仅导入定义以及插入参数/拾取点流程。当前缺共享目录配置、命令别名、画布跟随预览、资产管理操作和 DXF，不能称 L4 完成。
- `test_toolbar_library_imports_saved_definition` 初次断言通过但进程退出 134；诊断包含复现、gdb、同步扫描和禁用预览探针，定位到嵌套预览调用 `SketchCanvas.fit_view()` 相关的退出内存异常；改用预览专用范围计算和 `zoom_view_window`，扫描线程改为 QThread 并持有至 finished。定向真实窗口运行 offscreen 与 XCB/Xvfb 均 1 passed 且退出码 0；补充曲线和中文文字预览定位测试 1 passed。仅说明该定向场景通过，真实桌面尚未验收，也未宣称底层 fit_view 普遍修复。
- 修改 UI 七个路径 Ruff、format、basedpyright 通过。诊断时首次误判线程所有权为唯一原因，后通过关闭预览及禁用 fit_view 探针修正；用户数据未被改动。
- 下一入口：补共享根目录配置/添加移除、库资源的改名/回收、BLOCKLIB/WBLOCK、从 INSERT 入口进入库及放置动态预览、真实窗口跨文档验证；再做 DXF 和验收。
- 共享目录设置与 UI：新增 `ui/block_library_settings.py`，按路径生成稳定源 ID、持久化只读共享目录；浏览窗口添加/移除共享源，移除不删除目录文件，离线配置保留。设置往返 1 passed，窗口添加/移除 1 passed；相关路径 Ruff、format、basedpyright 通过。
- 退出异常继续排查：再次出现后，确认仅取消普通集合草稿和只浏览库均可正常退出，浏览并导入后立即取消可复现；无论取消画布预览还是隐藏预览都不足以稳定消除。将选择结果和存储对象从对话框冻结、延后到事件循环处理并安排对话框释放后，该场景在 offscreen 和 XCB/Xvfb 均 1 passed、进程退出 0；未将之前对 fit_view 的初步判断当作充分根因。等待用户真实桌面验证和继续覆盖快速关闭/异步扫描。
- 下一入口：完成库管理能力、BLOCKLIB/WBLOCK/INSERT 入口、真实画布实时预览与跨文件测试；解决对话框关闭/线程生命周期边界，再做 DXF 与交接。
- BLOCKLIB/WBLOCK 命令、重复命令及编辑菜单入口已接入；当前图纸无块执行 INSERT 直接进入块库，已有定义时插入对话框可选择块库。命令重复、空图插入和插入框入口各定向 1 passed；创建块直接相关旧回归 1 passed。主窗口/画布/命令栏等修改路径 Ruff、format、basedpyright 通过。
- `test_insert_library_in_new_drawing_and_reopen` 使用真实按钮、块库和插入参数，在新图纸中定位并提交；删除测试临时库目录后重开文件及撤销 1 passed。首次测试因为计时器早于异步放置窗口挂起，已终止专属进程并改为等待实际模态窗口；事件记录于 ledger。
- 补齐存储恢复记录：历史版本与回收项保存持久化回执，重建 store 后可恢复；新增 `test_recovery_receipts_survive_store_recreation` 红→绿 1 passed。进一步红测发现原子替换后目录 fsync 失败可能错误删除旧版本；现在无法确认旧文件仍在时保留恢复数据，定向故障测试及原写入失败测试 2 passed。存储测试 `uv run --no-sync pytest tests/libraries/test_block_store.py -q --tb=short` → 12 passed；修改路径 Ruff、format、basedpyright 通过。
- 剩余：库管理界面（重命名/删除/恢复）、跟随鼠标动态预览、字体缺失提示与异步扫描关闭边界、DXF 入库/导出、人工验收资料；跨文件真实桌面和 AutoCAD 待验收。
- 本地库列表重命名、移入回收站及从历史/回收记录恢复入口已接入；`test_local_library_rename_delete_and_restore` 红测缺按钮，实施后 1 passed；界面及测试路径 Ruff、format、basedpyright 通过。
- L5 开始：新增 `formats/block_library_dxf.py`，复用既有 DXF provider 读取块及导出定义＋原点实例；未引用块的非零基点/英寸换算与未知单位提示 2 passed。新增嵌套块测试先失败，发现现有普通 DXF 路径会隐藏只被嵌套块引用的有效子定义；为库导入增加显式读取选项，嵌套父块仍整体拒绝，受支持子定义可独立入库，定向 1 passed。既有嵌套/循环及单位导入关联回归 3 passed；DXF UI、实际输出预览与模型空间入库尚未完成。
- DXF 输出预览：提取共用 `_render_dxf_document`，块资产先生成 DXF 字节再从这些字节渲染；`test_preview_is_rendered_from_exact_export_bytes` 红→绿 1 passed，既有多草图输出预览直接回归 1 passed。
- 新增 DXF 块选择窗口及块库“导入 DXF / 导出 DXF”：支持多选、显示损失原因、未知单位时显式选择；导出使用现有实际字节预览确认。`test_dxf_selection_shows_issues_and_selects_multiple` 1 passed；`test_dxf_import_and_previewed_export` 初次断言通过但进程退出 139，诊断显示事件循环处理一段时间后可正常退出，现对两个模态子窗口按 Qt 生命周期安排释放，offscreen 与 XCB/Xvfb 定向测试各 1 passed 且退出码 0；不推断所有快速关闭组合已验证。
- 下一入口：模型空间作为块的明确入口、DXF 文本与专用 INSERT/损失边界、字体缺失提示和动态放置预览；补完工作包全链自检和人工交接。
- DXF 模型空间另存块：`read_dxf_modelspace_asset` 要求显式名称和毫米基点，预检不支持类型并核对模型空间对象数量与导入损失；英寸换算/基点及 INSERT 拒绝 2 passed。块库窗口提供独立导入入口，表单和真实窗口入库定向 2 passed。纯文字块与不支持嵌套块报告/导出 1 passed。
- 字体替代提示：选中库块时检查使用的文字样式，提示缺少字体和替代字体；定向红→绿 1 passed。块库操作按钮分为两排，避免横向溢出；用户提供名称/说明及错误反馈按纯文本显示。
- 画布交互：选中库块点“在画布指定插入点”后，复用冻结候选实时展开高亮预览；单击、Enter、右键确认，Esc 撤销预览，不提前写入任何定义/样式/图层。`test_library_insertion_canvas_preview_enter_and_cancel`：Enter 1 passed，右键 1 passed（offscreen 和 XCB/Xvfb 各一次），左键 1 passed，Esc 1 passed；跨测试参数时鼠标坐标未变化曾导致无 move 事件，修正测试先移动到其他位置。原 BLOCK/INSERT 画布取点直接回归 1 passed。变更路径 Ruff、format、basedpyright 通过。
- 下一入口：审计 L0–L5 未覆盖边界、后台扫描快速关闭、验证实际共享目录读取/锁层及 DXF 损失，再准备支持矩阵、样图和人工验收清单。真实桌面及 AutoCAD 验收仍待用户执行。

## 2026-11-26：L5/L6 补充边界与交接

- 对基准专用 INSERT 的辅助块建立失败测试：库扫描曾将其误列为普通块。为库导入单独排除基准与尺寸匿名块依赖图，普通嵌套父块的可支持子块仍可独立导入；`test_datum_helper_blocks_are_not_offered_as_library_assets`、`test_nested_block_rejected_but_its_supported_child_available` 和既有基准 GROUP 往返关联项 → 3 passed。
- `test_scan_ignores_stale_root_and_finishes_after_dialog_destroyed` → 1 passed：延迟返回的旧源结果不会覆盖新源，窗口销毁后扫描线程可完成；仅说明该定向场景，不代表所有桌面组合已验收。
- `test_export_fillet_draft_to_library_then_cancel_without_committing` → 1 passed：真实窗口画圆角、产生约束、保留源创建块，块管理保存到库，取消草稿不改变图纸历史且库文件仍可读。
- `test_insert_library_in_new_drawing_and_reopen[shared-readonly]` → 1 passed：共享只读来源入图、完成保存、删除测试库目录后重开及撤销；共享源禁用删除按钮。
- 新增 `docs/design/2026-11-26-external-block-library-manual-check.md` 和 `docs/examples/block-library/generate.py`；README 增加入口。生成器在全新临时目录成功运行，扫描为 4 个有效样例和 1 个坏文件报告，嵌套 DXF 返回 CHILD 与一条不支持报告。
- 用户真实桌面 Wayland/XCB、AutoCAD 2023/2025 和公差相关人工验收均未执行，清单标记待执行；自动测试不代替人工结果。未执行多轮全量测试。
- 最终计划核对发现保存对话框缺少原点预览、导入未向用户展示名称/图层冲突。新增定义预览并标明基点 `(0, 0)`、比例 1；导入在暂存前显示冲突处理方案，可取消，已有定义的无操作导入给出准确提示。
- `test_save_dialog_previews_definition_at_local_origin` 首轮缺少参数失败，实施后与保存失败保留输入、圆角草稿入库关联项 3 passed；`test_import_conflicting_library_definition_reports_and_can_cancel` 首轮因未报告冲突失败，实施后与真实草稿保存关联项 2 passed；原有工具栏导入完成场景 1 passed。
- `xvfb-run -a env QT_QPA_PLATFORM=xcb uv run --no-sync pytest tests/ui/test_block_library_workflow.py::test_export_fillet_draft_to_library_then_cancel_without_committing tests/ui/test_block_library_workflow.py::test_import_conflicting_library_definition_reports_and_can_cancel -q --tb=short` → 2 passed。
- 当前 Wayland 会话下 `QT_QPA_PLATFORM=wayland uv run --no-sync pytest tests/ui/test_block_library_dialog.py::test_save_dialog_previews_definition_at_local_origin tests/ui/test_block_library_workflow.py::test_import_conflicting_library_definition_reports_and_can_cancel -q --tb=short` → 2 passed；属于自动 GUI 测试，不是人工验收。
- 本次新增/调整的格式、DXF provider、UI、样例和测试路径 Ruff 与 format 检查通过；相关 basedpyright 0 errors。`git diff --check` 对本次接入的已跟踪路径通过。之前的分项结果仍以对应条目为准，不重复运行无关测试。
- 下一入口：用户按 `docs/design/2026-11-26-external-block-library-manual-check.md` 人工验收本地/共享块库及真实桌面；AutoCAD 2023/2025 和公差人工验收按用户要求后续补充。
