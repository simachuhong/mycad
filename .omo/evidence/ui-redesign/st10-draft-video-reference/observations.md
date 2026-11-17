# Solid Edge Draft 录像：版本核对及 U00 工程图参考

记录日期：2026-11-07。用户提供目录 `/home/sima/视频/SolidedgeST10-Draft`，包含 31 个 MP4、32 个 JPG 缩略图；`00` 只有 JPG。全部视频的原始文件名、时长、分辨率、大小和 SHA-256 见 [录像清单](inventory.json)，时间码均相对各自本地 MP4。视频总时长约 4.57 小时。本轮对每段视频取早期与中段两帧筛查，并对 01 号视频按 30 秒抽样、对部分关键区间加密取样；未逐帧或逐段完整观看。

## 版本按画面区分

目录名称不能证明每段视频均为 ST10。以下只登记画面标题可直接识别的样本；其余视频保留在清单中，尚未完成版本和内容核定。

| 视频 / 本地时间 | 画面可见版本和内容 | 范围 |
| --- | --- | --- |
| 01 `00:20` | [Solid Edge ST10 - Draft](v01-0020-draft-sheet.jpg)，图纸及 Draft 功能区。 | 本轮 U00 主要 ST10 Draft 参考。 |
| 02 `00:30` | [Solid Edge ST10 - Draft](v02-0030-st10-draft.jpg)，装配视图及零件表教程上下文。 | ST10 参考；装配零件表不据此视为 MyCAD 当前支持。 |
| 04 `03:53` | [Solid Edge ST10 - Draft](v04-0233-st10-bend-table.jpg)，钣金折弯表属性。 | ST10 钣金表视觉参考；不扩大本轮工程图承诺范围。 |
| 06 `00:30` | [Solid Edge ST10 - Draft](v06-0030-st10-hole-table.jpg)，孔表及图纸视图。 | ST10 孔表参考；表格操作未逐步核对。 |
| 03 `16:44`、05 `00:30` | [2019 模板画面](v03-1004-2019-template.jpg)、[2019 新建菜单](v05-0030-2019-new.jpg)。 | 作为 Solid Edge 2019 参考登记。 |
| 07 `00:30`、19 `00:30` | [2021 Draft](v07-0030-2021-draft.jpg)、[2024 Draft](v19-0030-2024-draft.jpg)。 | 分别作为 2021 和 2024 参考登记。 |

## 01 号录像与 MyCAD 的动作映射

来源：`01 - solid edge drafting tutorial-sheet setup-section view - detail view - d.mp4`，SHA-256 `2d826f53db9a50cefdeb211f85571d70520edae666b3b107f236cb225db85f1b`，1258.893 秒，1280×720；画面显示英文 ST10，维护包、实际系统缩放和输入设备未知。以下是选段画面与 MyCAD 自身工程证据的映射，不表示两软件已在相同条件下逐步比较。

| 本地时间 / ST10 画面 | 可直接观察的内容 | MyCAD 对应入口与已登记工程证据 | 差异及未证实事项 |
| --- | --- | --- | --- |
| `00:15–00:20` [模板入口](v01-0015-template.jpg)、[空图纸](v01-0020-draft-sheet.jpg) | 新建页高亮 ANSI Metric Draft；随后出现标题为 ST10 Draft 的空图纸。 | MyCAD 新建工程图后可建图纸；模型生成入口的自身窗口回归见 `test_generate_entry_creates_sheet_and_starts_canvas_placement`（[入口测试](../../../../tests/ui/test_drawing_start.py)）。 | 菜单组织、模板内容与实际创建步骤尚未人工并排比较。 |
| `01:00`、`02:00` [名称设置](v01-0060-sheet-name.jpg)、[背景图纸](v01-0120-sheet-background.jpg) | Sheet Setup 显示名称页及 Background 选项，背景列表和预览可见。 | MyCAD 图纸设置提供名称、幅面、比例、标题栏字段和内置/导入模板；[模板测试](../../../../tests/ui/test_drawing_templates.py)覆盖选中图纸设置及模板。 | ST10 的背景图纸机制与 MyCAD 模板机制须按实际设置和重开结果逐项对照。 |
| `06:15` [选择模型](v01-0375-select-model.jpg) | Draft 内打开 Select Model 文件对话框。 | MyCAD 独立工程图使用“选择工程图来源”，从会话已打开的零件/二维文档选择；关联路径见 `test_engineering_document_projects_its_attached_part`（[会话测试](../../../../tests/ui/test_document_session.py)）。 | ST10 画面显示文件选择；MyCAD 的会话来源选择与其入口不同。取消、缺失及重定位不能由该帧证明。 |
| `06:30`、`07:10` [视图布局向导](v01-0390-view-wizard.jpg)、[图纸上的视图](v01-0430-views.jpg) | 向导列出 front、iso 等主视图选项；后续图纸显示三个正投影视图和一个立体视图，树中有 Principal/Pictorial。 | MyCAD 先放基准视图，再放正投影视图；见 `test_place_base_then_first_angle_projected_view_without_committing`、`test_real_model_projection_is_placed_in_canvas`（[视图测试](../../../../tests/ui/test_drawing_views.py)）。 | 当前 MyCAD 盘点未发现立体视图及对应整组布局向导；不能把正投影视图测试当作这些能力。 |
| `08:30`、`09:30` [剖视结果](v01-0510-section.jpg)、[局部详图预览](v01-0570-detail-preview.jpg) | 图纸显示 SECTION A-A 剖视及剖切线；Detail 命令中显示局部圆形区域和放置提示。 | 现有 MyCAD 工程图盘点覆盖正投影视图及其显示设置。 | 剖视和局部详图未盘为 MyCAD 已有能力；09:30 处于预览，不能据此认定该次详图已确认。 |
| `13:00` [工程图尺寸](v01-0780-dimension.jpg) | Draft 画布显示水平/垂直尺寸、尺寸工具条与被选中的标注控制点。 | MyCAD 投影视图支持关联测量标注；见 `test_supported_annotation_kinds`、`test_canvas_annotation_placement_and_text_drag_are_bus_commands`（[标注测试](../../../../tests/ui/test_drawing_annotations.py)）。 | 静帧不能证明每条 ST10 尺寸的创建步骤、驱动语义或源模型关联规则；MyCAD 工程图测量尺寸不驱动模型。 |
| `15:25–15:33` [零件模型尺寸](v01-0925-part-dimensions.jpg)、[视图过期警告](v01-0930-stale-warning.jpg)、[更新入口](v01-0932-update-entry.jpg)、[更新处理中](v01-0933-update-processing.jpg) | 先显示 ST10 Ordered Part 模型及尺寸；切回 Draft 后弹窗提示视图过期及在过期视图上放置的尺寸更新时会失联；随后指针停在 Update Views 上，状态栏显示正在处理第 5/6 个视图 SECTION A-A 的几何。 | MyCAD 有更新视图、失联标注提示/重附着及出图守卫；见 `test_failure_preserves_last_result_and_requires_retry`、`test_orphan_keeps_text_position_and_blocks_scene`、`test_reattach_preserves_identity_and_expression` 和 `test_export_action_uses_current_clean_scene_and_blocks_stale`（[更新](../../../../tests/ui/test_drawing_updates.py)、[标注](../../../../tests/ui/test_drawing_annotations.py)、[输出](../../../../tests/ui/test_drawing_pdf.py)测试）。 | 已抽帧能证明 ST10 显示警告并开始处理视图更新；尚未确认来源几何被修改或全部更新成功，不能将此写成完整源修改→更新成功链。两软件失联语义也尚未实机比较。 |

## 证据层次和余项

补充抽帧：`07:40` [来源视图高亮](v01-0460-section-source.jpg)，`07:50` [剖切线](v01-0470-section-line.jpg)，`08:00` [剖视放置](v01-0480-section-placement.jpg)，`08:10` [剖面线结果](v01-0490-section-hatching.jpg)，`09:10` [详图显示](v01-0550-detail-placed.jpg)。这些帧可支持上述步骤和显示状态，不单独证明点击、键盘或选项的全部顺序。等轴测源码入口已在后续增量中加入，尚未做行为或人工验证；整组向导、剖视及详图仍待实现。

- **参考录像：** ST10 Draft 的新建、设置、模型选择、视图、剖视/详图、尺寸和过期警告已有选段。ST9 V10/V11 仍保留为独立版本参考。01 号录像尚未完整逐段复核；源模型几何修改、更新成功、保存重开和 PDF/DXF 输出尚无本轮可确认的连续证据。
- **MyCAD 源码与自动测试：** 上表引用的是当前可定位的源码入口和既有测试名称；此前 U10 自动结果见 [U10 基线](../u10-baseline.md)及[工程图动作盘点](../u00-drawing-actions-2026-11-07.md)。本轮未运行代码测试。本轮首次核对时 `main_window.py` SHA-256 为 `9d95a5a2c369442cf32bab4a4900092abd3b3d4fe64b4a5558cd9d0e8f00b1e7`，校验时已因并行工作变为 `180df875ae47f71a2ef155bdd5319c913d63a654cb5528a8c8d6dbf3072c8bc0`；这两个值均是读取时点的快照；`drawing_workbench.py` 为 `66a8df9d26bb94f7e3ec82c1727ef9b741a9d553cecc5daa4ac7198a48850424`，`drawing_updates.py` 为 `d71ea41002f53820e54ed57da5d4308ee2b2835a75a80dc551fadaaddc67532a`。此前测试结果是各自运行时的记录，不自动证明当前共享工作区全部行为。
- **参考软件核对：** 尚未在实际 ST10 和 MyCAD 上以相同几何、图纸幅面/比例、语言、窗口及显示缩放逐步操作比较。ST10 `.par` 与 MyCAD 文档格式不同，比较时应准备几何和参数相同的各自来源文件，并记录不支持项。
- **用户验收：** 仍需实际操作来源选择→视图→标注→修改来源→更新→保存重开→PDF/DXF 输出，在目标查看器检查结果后由用户逐项确认。截图、软件渲染和自动回归不代替用户签收。U00 保持未完成。
