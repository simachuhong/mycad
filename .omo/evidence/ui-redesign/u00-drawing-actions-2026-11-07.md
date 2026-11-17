# U00 工程图动作与入口盘点

日期：2026-11-07。基线提交 `404b5a3`。本表核对当前工作区的工程图 UI 路由、条件、处理和既有测试；工作区有 U01/U09 等未提交改动，因此哈希对应下方记录的工作区源码快照，不代表基线提交本身。源码存在、测试通过或 Xvfb 截图均不等于 ST10 Draft 对照或用户验收完成。

范围参考：[U00 基线](u00-baseline.md)、[统一 UI 中期余项](../../../docs/design/2026-11-06-unified-ui-midterm-remaining.md)、[U10 工程图回归基线](u10-baseline.md)。本表补充工程图动作，不取代 U10 功能验证，也不将 ST9 Draft 样本标为 ST10。

## 路由与动作

主入口为 `MainWindow` 中的 `DrawingWorkbench`。普通单文档窗口和多文档会话都会把工程图工作台放入 Drawing 工作区；活动工程图的操作写入其 `LoadedDocument.bus`。多文档来源按钮要求 `DocumentSession` 可用，来源选择器只列出当前会话中已打开的零件和独立二维文档。

| 动作 | 入口与启用条件 | 实际处理与范围 | 自动验证映射 |
| --- | --- | --- | --- |
| 新建图纸 | 工程图工具栏“新建图纸”；空图纸页的模型/草图放置可先暂存来源再自动创建图纸。需有已绑定文档，且当前没有未完成视图、文字、标注或视图编辑。 | 提交 `drawing.sheet.create`；幅面、模板、投影角、比例、名称和标题栏值来自当前设置。工作台提供多图纸树导航；本次未发现独立“删除图纸”工具栏入口。 | `test_builtin_selection_fields_and_undo`、`test_sheet_settings_only_update_the_selected_sheet`（[模板测试](../../../tests/ui/test_drawing_templates.py)）；视图流程见 `test_generate_entry_creates_sheet_and_starts_canvas_placement`（[入口测试](../../../tests/ui/test_drawing_start.py)）。 |
| 选择/更新/解除来源 | Drawing 空页面“选择工程图来源…”；文档菜单还有“选择工程图来源”“查看来源状态”“更新来源引用”“解除来源关联”。来源按钮在工程图空页显示；需有多文档会话才启用，忙碌时禁用。菜单选择要求活动工程图并且没有未提交几何。 | 选择已打开的零件或独立二维文档；二维来源还需选择已完成草图。经 `reference.attach` 等命令记录关联。来源关闭或缺失时，“更新来源引用”可定位文件，但会核对文件身份；不允许仅凭路径/文件名换成另一个文件。来源引用更新后仍需“更新视图”重算投影。取消选择不写命令。嵌入式、无文档会话窗口禁用来源选择。 | `test_source_selection_is_disabled_without_document_session`（[入口测试](../../../tests/ui/test_drawing_start.py)）；`test_engineering_document_projects_its_attached_part`、`test_engineering_document_places_attached_sketch`、`test_cancelling_engineering_source_selection_keeps_document_unchanged`、`test_pending_view_edit_blocks_reference_commands`（[文档会话测试](../../../tests/ui/test_document_session.py)）。更多失效/重定位回归记录在 [U10 基线](u10-baseline.md)，本表未重跑。 |
| 模型投影视图 | 空页面“从当前三维模型生成投影视图”或工具栏“从模型生成投影”；只有活动来源可提供实体且工作台不忙时启用。 | 创建图纸后在画布点放基准，再沿方向放置投影视图；当前方向列表为前、后、俯、仰、左、右，第一角/第三角设置影响排列。一次提交生成关联的一组投影视图。模型来源快照和投影在后台处理；来源修订变化会让草稿暂停，更新后再继续。没有据此推定剖视、局部视图或等轴测视图已实现。 | `test_place_base_then_first_angle_projected_view_without_committing`、`test_escape_discards_entire_uncommitted_group`、`test_canvas_group_enter_and_undo`、`test_real_model_projection_is_placed_in_canvas`、`test_changed_model_pauses_uncommitted_placement`（[视图测试](../../../tests/ui/test_drawing_views.py)）。 |
| 草图平面视图 | 空页“放置草图平面视图”或工具栏同名动作；仅有已完成草图且工作台不忙时启用。来源可为当前文档或经来源关联的独立二维草图。 | 按草图局部 U/V 坐标生成并放置单个平面视图，不等于从实体生成多视图。草图来源消失或为空时拒绝。 | `test_engineering_document_places_attached_sketch`（[文档会话测试](../../../tests/ui/test_document_session.py)）；入口与图纸创建见 `test_generate_entry_creates_sheet_and_starts_canvas_placement`。 |
| 视图选择与编辑 | 画布点选或图形信息树选择；选中视图后启用右侧“视图”页和“删除视图”。视图比例、隐藏线、相切线、对齐只作用于选中视图。 | 比例可设定或恢复继承；子视图可解除/恢复对齐；隐藏线/相切线可覆盖或恢复继承显示。画布拖动位置和比例先预览，松开提交；Esc 取消。删除预览包含后代投影视图及其标注，Enter 确认、Esc 取消。未完成操作会阻止跨图纸/视图切换、其他命令、保存关闭及出图。 | `test_switching_sheet_preserves_view_move_preview`、`test_switching_sheet_preserves_pending_view_deletion`、`test_pending_view_edit_blocks_starting_another_command`、`test_pending_view_edit_blocks_window_close`（[视图测试](../../../tests/ui/test_drawing_views.py)）。 |
| 尺寸标注 | 工具栏“尺寸标注”菜单及右侧“标注”页；先在干净投影视图选几何，再在画布放置文字。 | 支持水平、垂直、对齐、半径、直径、角度尺寸和中心标记/线。工程图尺寸为关联测量尺寸，不驱动模型；双几何尺寸要求几何来自同一视图。模型/来源修订变化后标注可能失联，保留原文字位置并阻止出图；可尝试在画布重附着。右侧可改精度、前后缀或删除。 | `test_canvas_annotation_placement_and_text_drag_are_bus_commands`、`test_supported_annotation_kinds`、`test_reattach_preserves_identity_and_expression`、`test_model_change_during_annotation_draft_prevents_commit`（[标注测试](../../../tests/ui/test_drawing_annotations.py)）。 |
| 文本说明 | 工具栏“文本标注”或右侧“文本”页。当前图纸可用，忙碌状态禁用。 | 在画布编辑、拖动和删除文字；Ctrl+Enter 完成，Esc 取消。内容作为图纸文字，不与模型关联。 | `test_text_in_canvas_edit_move_delete_undo_and_pdf`、`test_text_cancel_and_document_switch_preserve_no_draft`、`test_new_sheet_preserves_active_text_until_completion`（[文字工具测试](../../../tests/ui/test_drawing_note_tools.py)）。 |
| 更新视图 | 工具栏“更新视图”在文档绑定后启用；没有待更新目标时不产生投影工作。自动刷新也会检查所有图纸中的视图来源指纹/方向。 | 与“更新来源引用”分开：前者按当前已采用来源重算过期投影；草图投影直接重算，实体投影先取快照再送后台 worker。按会话、视图、来源指纹和代次丢弃过期结果；失败保留旧结果并标记需重试。取消表示不再接收本次结果，不声称后台进程已被强制终止。 | `test_stale_same_session_result_is_discarded`、`test_layout_only_sync_does_not_reproject`、`test_failure_preserves_last_result_and_requires_retry`、`test_workbench_coalesces_model_changes_and_recovers_worker`（[更新测试](../../../tests/ui/test_drawing_updates.py)）。 |
| 图纸设置与模板 | 右侧“设置”“模板”页；先选图纸后应用。含 GB、ISO、旧式简单图框及导入 DXF 模板。 | 图纸设置包含幅面、第一/第三角、默认比例、名称和标题栏字段；改设置只更新所选图纸，已有视图位置和比例保持。DXF 导入允许选布局、单位、幅面、原点偏移和文字字段映射，需先预览再存入本地模板库；模板预览不等于已经应用到图纸。 | `test_embedded_custom_size_survives_settings`、`test_import_preview_mapping_and_cancel_leave_document_untouched`、`test_import_entry_saves_library_without_applying_to_document`、`test_template_pdf_dxf_and_rotated_text`（[模板测试](../../../tests/ui/test_drawing_templates.py)）。 |
| 输出 | 工具栏“导出 PDF”或“导出 DXF”，弹出保存对话框；当前图纸需就绪。 | 只输出活动图纸；视图必须是最新且无未提交文字、标注、放置、移动或删除预览。输出前校验场景。PDF 为矢量和实际纸张尺寸，缺字会拒绝；DXF 为静态交付，不保留跨软件模型关联。写入临时文件成功后原子替换目标文件。扩展名缺失时按所选格式追加。 | `test_export_action_uses_current_clean_scene_and_blocks_stale`、`test_output_is_blocked_during_uncommitted_view_edit`、`test_pdf_media_box_and_vector_content`、`test_invalid_pdf_preserves_existing_file`、`test_writer_failure_keeps_original_and_cleans_temporary`（[PDF/出图测试](../../../tests/ui/test_drawing_pdf.py)）；真实 DXF/PDF 文件链也见 `test_engineering_document_projects_its_attached_part`。 |

## 人工证据与待核项

| 项目 | 现有证据 | 结论 |
| --- | --- | --- |
| MyCAD 工程图空页画面 | [U10 工程图来源截图](u10-engineering-source.png)，1366×900、Xvfb/xcb、软件 OpenGL；脚本创建未保存工程图。 | 证明该取证配置下来源入口可见，不证明真实 GPU、鼠标完整流程或 ST10 行为。 |
| 自动关联、投影、更新、标注、保存和输出 | [U10 回归基线](u10-baseline.md)记录了真实工程图会话的自动流程、PDF/DXF 非空输出、保存重开、来源缺失/身份校验/恢复，以及关联标注失效与重附着测试。 | 是 MyCAD 自动验证记录；本轮只核对测试名/源码映射，没有复跑这些测试。 |
| Solid Edge 参考 | [ST10 Draft 新录像选段](st10-draft-video-reference/observations.md)已覆盖图纸、来源、视图、尺寸和过期警告；[ST10/ST9 选段对照](st10-st9-crosscheck.md)单列 ST9 V10/V11。 | ST10 参考已取得；来源几何修改→更新成功的连续证据和同条件人工对照仍待确认。 |
| 人工和用户验收 | U10 明确记载实机操作与参考对照待完成；没有工程图全链人工录像或用户签收记录。 | 待办。未宣称实机对照或用户验收完成。 |

待补资料/人工项：取得可核对的 ST10 Draft 工程图参考画面或录像（语言、缩放、图纸模板和操作时间码）；按人工流程复现来源选择、放置视图、尺寸/文字标注、来源修改、更新、保存重开和 PDF/DXF 输出；核对来源关闭/重选、多草图来源、标注失联修复、视图删除与多图纸导航；用实际目标 CAD/PDF 查看器核对导出结果。章节截图与自动测试不替代这些项。剖视、局部视图、等轴测视图及 DWG 等本轮未盘为已有功能，需由产品范围另行决定是否排期。

## ST9 V10/V11 Draft 片段与 MyCAD 映射（2026-11-07）

下表只使用 [ST9 V10/V11 观察记录](st9-video-reference/observations.md)中的本地视频时间码和静帧；V10、V11 视频源哈希、分辨率及画面语言见该记录。ST9 是可追溯的 Draft 参考，不是 ST10 证据。V10 的 `00:30` 是布局选择过程画面，V10 `01:10` 是最终图纸画面；单帧不提供完整按键顺序。

| ST9 Draft 参考片段 | 参考画面能确认的动作 | MyCAD 对应入口与自动证据 | 当前差异 / 证据状态 |
| --- | --- | --- | --- |
| V10 `00:10–00:15` [目前模型的图纸入口](st9-video-reference/v10-0010.png) / [入口选取](st9-video-reference/v10-0015-current-model-drawing-entry.png) | 应用菜单列出从当前模型建图与工程图模板；00:15 当前模型图纸选项高亮。 | `DrawingWorkbench` 的模型生成入口可建图纸并开始画布放置；`tests/ui/test_drawing_start.py::test_generate_entry_creates_sheet_and_starts_canvas_placement`。 | 入口组织不同；自动测试覆盖 MyCAD 自身路由，不是 ST9/ST10 同条件比较。静帧未显示创建完成。 |
| V10 `00:30–00:35` [布局条](st9-video-reference/v10-0030.png) / [布局对话框](st9-video-reference/v10-0035-view-layout-dialog.png) | 字幕说明选择三视图和等角图；对话框可见视图列表与确认/取消。 | MyCAD 以基准视图开始，再逐个放置正投影视图；`tests/ui/test_drawing_views.py::test_place_base_then_first_angle_projected_view_without_committing`、`test_real_model_projection_is_placed_in_canvas`。 | MyCAD 当前未盘到等角视图或一次选择三视图加等角图的布局向导；抽帧不能确认 ST9 选择最终提交。 |
| V10 `00:45` [视图放置](st9-video-reference/v10-0045-view-placement.png) | 画布显示多个投影及等角视图，字幕转入视图标注尺寸。 | MyCAD 提供基准视图和投影视图放置；同上两项视图测试。 | ST9 帧仍有高亮/命令条状态；MyCAD 的分步视图操作不是整组布局向导。 |
| V10 `00:50–00:55` [取回尺寸提示](st9-video-reference/v10-0050.png) / [尺寸可见](st9-video-reference/v10-0055-dimensions-visible.png) | 功能区出现取回尺寸提示；00:55 已能看见多处尺寸，字幕还提到用 Smart Dimension 补充。 | MyCAD 由投影视图曲线创建关联测量标注；入口和测量类别见 `tests/ui/test_drawing_annotations.py::test_supported_annotation_kinds`、`test_canvas_annotation_placement_and_text_drag_are_bus_commands`。 | 取回模型已有尺寸的入口/语义尚未在 MyCAD 盘到；手动创建测量标注不能作为自动取回的等价实现。静帧也不能区分已有/新增尺寸。 |
| V10 `01:10` [图纸结果](st9-video-reference/v10-0070.png) | 可见图框、标题栏、三个正投影视图、等角图和尺寸。 | MyCAD 图纸模板、标注和输出由 `tests/ui/test_drawing_templates.py::test_template_pdf_dxf_and_rotated_text`、`tests/ui/test_drawing_pdf.py::test_pdf_media_box_and_vector_content` 覆盖；源视图生成见 `test_real_model_projection_is_placed_in_canvas`。 | MyCAD 的模板字段/标注/PDF-DXF 有自动证据；等角视图缺口仍在。该静帧不能证明源更新、重开或输出。 |
| V11 `00:10` [图纸双击进入模型](st9-video-reference/v11-0010.png) | 字幕说明双击图纸后打开对应三维文件。 | MyCAD 工程图可关联已打开来源；来源选择和工程图来源链见 `tests/ui/test_document_session.py` 及 [U10 基线](u10-baseline.md)。 | 当前画布双击处理文字/尺寸编辑；未找到从视图双击打开来源模型的路由或对应测试。来源关联不等于该导航入口。 |
| V11 `00:15–00:25` [模型上下文](st9-video-reference/v11-0015-model-edit-context.png)、[面编辑预览](st9-video-reference/v11-0020-sync-face-edit-preview.png)、[修改画面](st9-video-reference/v11-0025.png) | ST9 同步零件中的圆柱/孔区域高亮并出现操纵器与尺寸输入，字幕提示移动 5 mm 后返回工程图。 | MyCAD 来源变更后经 `drawing_updates.py` 重算投影；自动更新边界见 `tests/ui/test_drawing_updates.py`。 | ST9 画面属于同步直接面编辑；MyCAD 没有该同步操纵器/面移动求解。工程图更新链不覆盖这项编辑语义。 |
| V11 `00:30–00:35` [待更新线索](st9-video-reference/v11-0030-stale-view-prompt.png) / [更新视图命令](st9-video-reference/v11-0035-update-view-command.png) | 返回 Draft 后字幕指出视图中有线需要更新；随后指向“更新视图”命令并显示说明。 | MyCAD 有来源刷新/重投影路径；自动更新边界见 `tests/ui/test_drawing_updates.py::test_workbench_coalesces_model_changes_and_recovers_worker`、`test_failure_preserves_last_result_and_requires_retry`。 | 录像静帧不能证明 ST9 更新结果；MyCAD自动刷新和命令状态不构成 ST9 提示/对话框行为对照。 |
| V11 `00:40–00:50` [尺寸跟踪反馈](st9-video-reference/v11-0040.png)、[跟踪器细节](st9-video-reference/v11-0045-dimension-tracker.png)、[警示尺寸](st9-video-reference/v11-0050-tracker-warning.png) | 对话框显示一项变更尺寸 55.00；图纸局部有警示三角和尺寸。 | MyCAD 投影/几何引用失联时保留尺寸文字位置并将场景标为问题；可显式重附着。相关测试：`test_missing_projection_retains_annotation_warning_position`、`test_reattach_preserves_identity_and_expression`。 | 状态提示和修复入口不等同 ST9 尺寸跟踪器；静帧不能证明自动更新或修复步骤。MyCAD 输出遇到失效标注会被拦截，见 `test_export_action_uses_current_clean_scene_and_blocks_stale`。 |
| V11 `00:55` [返回后的图纸](st9-video-reference/v11-0055.png) | 视图和标注仍可见，字幕转入工程图尺寸修改说明。 | MyCAD 来源更新/投影刷新与失败恢复见 `test_workbench_coalesces_model_changes_and_recovers_worker`、`test_failure_preserves_last_result_and_requires_retry`；完整自动来源链与输出记录见 [U10 基线](u10-baseline.md)。 | 这是静态结果帧；不能证明更新数值、保存重开、失败恢复或 MyCAD/ST9 行为等价。自动回归不算人工对照。 |

### ST10 Draft 与用户验收待办

- **参考资料仍待核对：** 新提供的 [ST10 Draft 录像](st10-draft-video-reference/observations.md)已补图纸、来源、视图、尺寸、过期警告和更新处理中样本。当前抽帧尚未证明来源几何修改、全部更新成功及标注关联结果；维护包、系统缩放和部分视频完整步骤仍待核对。旧零件录屏的 10 秒筛查只适用于[原录像](st10-video-reference/observations.md)。
- **缺少的同条件对照：** 用几何和参数相同的各自零件文件、相同图纸目标，在 ST10 Draft 与 MyCAD 各执行并录下“建图 → 放置视图 → 尺寸/文字标注 → 改源 → 更新 → 保存关闭重开 → PDF/DXF 输出”。记录两端的实际版本、语言、显示分辨率/缩放、图纸幅面/比例和输入设备；若其中一端不支持某一步，保留原样并登记功能差异，不补写成通过。
- **用户验收步骤：** ① 用户确认两端模型的几何、参数和图纸目标一致；② 实际逐步操作并检查视图位置/方向、标注值与关联状态、来源更新后的失效提示/修复、保存重开后的来源和图纸状态；③ 在目标 PDF/DXF 查看器打开导出文件，检查纸张、图框、视图、尺寸和文字；④ 用户逐项签收或列出差异与后续范围。Xvfb 自动回归、脚本生成截图和录像静帧均不能替代这一步。

## 可追溯快照

SHA-256 针对 2026-11-07 本次盘点的工作区文件；若同一工作区后续变更，应重算对应文件哈希。测试文件用于定位既有覆盖。共享工作区在测试运行期间由并行工作改动了 `main_window.py`；盘点起始读取哈希为 `f21d6f629bfef2ba108503c140df8e6e98b2564ff585cadb96b86ace3b3d3b81`，当时复核的文件哈希为下表值。复核该文件差异只涉及独立二维修剪/延伸历史确认与文档保存路径守卫，不涉及本表引用的工程图入口/来源路由；工程图入口相关定向测试随后按当时工作树复跑。

```text
35e7193579108cfb036302724ed47430649b915f4650fcbad28419ed60d2de46  src/mycad/ui/main_window.py
66a8df9d26bb94f7e3ec82c1727ef9b741a9d553cecc5daa4ac7198a48850424  src/mycad/ui/drawing_workbench.py
b5ad02561bff02abf15254e8e357ab46a18e55467af2059ba2f8734fc3770139  src/mycad/ui/drawing_canvas.py
4e5051af2334da8071a6fb61370a57fe9a85b80fd547b7ff08a3fe920e9279a8  src/mycad/ui/drawing_templates.py
b69a45993f93d10c9a2047e80eb68e422226e97416e85552ce5bf2df888a1287  src/mycad/ui/drawing_annotation_tools.py
b19fa956b6b5451a08bed1642fa8d90bbd9fdf6b85c9a94890f39dc6fb06122d  src/mycad/ui/drawing_note_tools.py
d71ea41002f53820e54ed57da5d4308ee2b2835a75a80dc551fadaaddc67532a  src/mycad/ui/drawing_updates.py
b25243b940cef00248f15bbc83baaa1f1afa403816124582b77726e175189bcf  src/mycad/ui/drawing_render.py
868f86167708e793faa8757cdd0f313f0dfc0884c98bb507b892057f6a8297c1  src/mycad/ui/drawing_pdf.py
f047f885b8bdbca3ee3ecb652b262034f9f09b2c56d698d32e467709c30d4890  src/mycad/formats/drawing_export.py
228493202e085c9cc2aef3d7fecd81cd3e7a82e4d1d77fc04acec1503b525f96  src/mycad/core/drawing.py
797ce74dcf804c1d655cc5ada3b079482711dba44e14c554129793302658a600  src/mycad/core/drawing_projection.py
b0a01f109c889701ed5f0ce4b94b1562daebd4a3e67df9322bdbfaa95627bd89  src/mycad/core/drawing_annotations.py
d5b5f666900e771bf20d7f08cede1703b671a5a8b3c39bb4977363474f5f5531  src/mycad/core/drawing_templates.py
b30438fe6216bfe4f1823988fa4656c8253ee551426073a1a643040f11d0c0e5  src/mycad/core/drawing_references.py
8a9edadd7bac7b3ca3bde972b39bc391a67e9f7b56e280fb0934bf4ada1ef212  src/mycad/core/document_references.py
```

原始工程图动作盘点依据源码入口、既有测试名和 U10 已登记结果；该轮只新增本证据文档，没有修改应用代码。初始 scoped 回归命令 `xvfb-run -a uv run pytest tests/ui/test_drawing_start.py tests/ui/test_document_session.py tests/ui/test_drawing_templates.py tests/ui/test_drawing_views.py tests/ui/test_drawing_updates.py tests/ui/test_drawing_annotations.py tests/ui/test_drawing_note_tools.py tests/ui/test_drawing_pdf.py -q` 结果为 **121 passed**（411.84 秒）。并行工作期间 `main_window.py` 更新后，按当时工作树复跑 `xvfb-run -a uv run pytest tests/ui/test_drawing_start.py tests/ui/test_document_session.py::test_engineering_document_projects_its_attached_part tests/ui/test_document_session.py::test_engineering_document_places_attached_sketch tests/ui/test_document_session.py::test_cancelling_engineering_source_selection_keeps_document_unchanged -q`，结果为 **7 passed**（33.71 秒）。U00 仍未完成，待办与人工证据缺口如上。
