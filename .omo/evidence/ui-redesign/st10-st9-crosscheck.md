# Solid Edge ST10 / ST9 模式与 MyCAD 对照

日期：2026-11-07。此记录核验目前已经抽样的本地片段，并按本地录像时间标注；它不是完整观看报告，也不是实机或用户验收。

## 来源与模式边界

- ST10 来源为 `/home/sima/视频/solidedge_st10_01.mp4`，SHA-256 `fefd2770de2c5876edc074c32319048af06ffd3438e0faae22fe2f0a2a2953db`。本机 `ffprobe` 核对为 1920×1080、714.30875 秒。它是浏览器播放教程的录屏，以下时间是这份本地录屏的时间；画面中的 Solid Edge 标题/树用于判断模式，不用网页标题替代。
- ST9 来源是 `/home/sima/视频/Solid Edge 同步建模/` 下分别编号的课程片段。本次再次核对 V02（85.426213 秒、1280×720）、V03、V09 的文件哈希，均与[现有 ST9 取样登记](st9-video-reference/observations.md)一致。V01–V09 是同步零件课程片段；V10/V11 为工程图场景，不归入有序或同步零件模式。各片段的时间码相对于各自 MP4。
- ST10 模式切换的关键证据：00:10 标题和树显示 `Synchronous Part` / `Synchronous`；00:15 的 Tools 页显示 `Synchronous` / `Ordered` 选项；00:17 抽帧直接显示 `Solid Edge ST10 - Ordered Part` 和 `Ordered` 树。00:20 的选面及 00:27 的草图线属于随后记录的有序环境。00:17 的裁剪图保存在 [ST10 有序模式画面](st10-video-reference/recording-0017-ordered-mode.png)。
- ST9 V02 在 00:40–01:20 直接展示同步环境中的矩形输入和完成；V03 为同步环境中的区域到实体；V09 展示同步模型面编辑。不能把这些 ST9 片段记成 ST10 同步操作。ST10 本地录屏只取到同步空闲/模式切换画面，没有同步操作段证据。
- MyCAD 本轮现有三维命令、零件草图和特征链不包含 Solid Edge 同步求解器或方向盘式直接移动面。几何适配层也明确说明[平面面拉伸](../../../src/mycad/geom/_b123_features.py)不是通用同步面移动求解器；完整同步建模在[U14 后续专项](../../../docs/design/2026-11-04-unified-ui-todo.md)范围。

## ST10 已取样片段

| 本地时间 / 模式 | 观察到的操作 | MyCAD 代码与自动测试映射 | MyCAD 人工对照证据 |
| --- | --- | --- | --- |
| 00:10–00:17；先同步空闲，00:17 已有序 | 空模型同步界面；Tools 页切换选项；随后有序标题/树出现。 | MyCAD 没有对应的有序/同步模式切换入口或同步零件工作台/测试。 | 无匹配 MyCAD 模式画面或实机操作记录；见 [ST10 取样原记录](st10-video-reference/observations.md)。不据此认定模式转换能力。 |
| 00:20–00:27；有序 | 先启动 Sketch、选平面；进入草图后用带 Length/Angle 字段的线工具。 | [零件草图工作台](../../../src/mycad/ui/part_sketch_workbench.py)、[动态输入](../../../src/mycad/ui/sketch_dynamic_input.py)；`test_resident_rectangle_entry_selects_tool_before_plane`、`test_tool_then_pick_model_face_and_lock`、`test_locked_line_dimensions_match_preview_and_committed_geometry`（[测试文件](../../../tests/ui/test_part_sketch_workbench.py)）。 | 有 Xvfb 截图和自动交互测试，没有物理屏幕/真实 GPU 上与 ST10 同步或有序操作的对照；见 [U04](u04-progress.md)、[U05](u05-progress.md)。 |
| 01:59–02:11；有序 | 折线草图中编辑水平尺寸，随后画布显示 350 与 150 标注。 | [草图尺寸](../../../src/mycad/ui/part_sketch_dimensions.py)与[零件草图工作台](../../../src/mycad/ui/part_sketch_workbench.py)；`test_canvas_dimension_selects_geometry_and_places_annotation`、`test_edit_driving_dimension_refreshes_reference_and_downstream`（[测试文件](../../../tests/ui/test_part_sketch_workbench.py)）。 | [软件渲染尺寸图](u06-draft-dimensions-xvfb.png)不是 ST10 对照画面；驱动/参考、冲突修正和输入优先级的实机对照仍未留证，见 [U06](u06-progress.md)。 |
| 09:45–10:10；有序模型上下文中的 Hole 草图 | 端面圆草图、⌀12 标注、Close Sketch 返回入口；随后回到 Ordered Part 并出现 Hole 命令条。 | MyCAD 有[零件草图/建模入口](../../../src/mycad/ui/part_sketch_workbench.py)、[绑定孔任务](../../../src/mycad/ui/bound_hole_task.py)和独立 `feature.hole`；测试包括 `test_sketch_hole_previews_and_commits_against_selected_planar_face`、`test_bound_hole_select_preview_and_commit_upgrade`（[建模测试](../../../tests/ui/test_modeling_interaction.py)、[绑定孔测试](../../../tests/ui/test_bound_hole_task.py)）。绑定孔升级、草图圆孔和 ST10 Hole 命令的流程语义不同。 | 现有软件窗口截图/自动流程没有记录 ST10 的同条件端面草图与孔命令人工对照；[U11 进度](u11-baseline.md)仍将参考软件及人工验收列为待办。 |
| 10:35–10:50；标题为 Part1: Pattern 的草图环境 | 圆周草图阵列输入 Radius/Sweep/Count/Spacing，并显示预览。 | MyCAD 的零件草图工作台没有该类草图阵列工具或对应测试。`feature.hole_pattern` 的[建模条](../../../src/mycad/ui/modeling_toolbar.py)及 `test_hole_pattern_previews_selected_face_and_commits_all_instances`（[测试文件](../../../tests/ui/test_modeling_interaction.py)）是孔阵列，不是草图图元阵列，不能代替。 | 未记录同类 MyCAD 实机操作或人工画面对照。ST10 抽帧显示输入与预览，不证明提交、撤销或完整阵列行为。 |

## ST9 已取样片段

| 片段 / 模式 / 时间 | 观察到的操作 | MyCAD 代码与自动测试映射 | MyCAD 人工对照证据 |
| --- | --- | --- | --- |
| V01 同步；00:20、00:50、01:20、01:50 | 文件入口、同步工作区、线工具长度/角度、基准平面候选。 | MyCAD 有[零件草图工作台](../../../src/mycad/ui/part_sketch_workbench.py)及线输入；可参考 `test_locked_line_dimensions_match_preview_and_committed_geometry`、`test_tool_then_pick_model_face_and_lock`（[测试文件](../../../tests/ui/test_part_sketch_workbench.py)）。它们测试的是 MyCAD 有序式草图链，不是同步模式切换或同步约束。 | 未留 ST9 与 MyCAD 的实机并列操作；自动截图不能证明模式或选面语义等价。 |
| V02 同步；00:40–01:20 | XZ 平面矩形；宽、 高、角度动态字段；Tab 输入提示；Enter 完成。 | [零件草图动态输入](../../../src/mycad/ui/sketch_dynamic_input.py)；`test_locked_rectangle_and_circle_dimensions_commit_exact_values`、`test_resident_rectangle_entry_selects_tool_before_plane`（[测试文件](../../../tests/ui/test_part_sketch_workbench.py)）。MyCAD 测试覆盖精确矩形值，不覆盖 ST9 同步求解/ Tab 规则的等价性。 | [MyCAD 线草图截图](u05-line-session-1024.png)是 Xvfb 布局证据，非矩形实机对照；[U05](u05-progress.md)记载真实 ST10 操作核对待办。 |
| V03 同步；00:10、00:40、00:50–00:58 | 选择闭合区域；对称实体预览；输入厚度并完成。 | [区域到特征路径](../../../src/mycad/ui/part_sketch_workbench.py)；`test_selected_region_from_sketch_drives_extrude` 和 `test_symmetric_sketch_extrude_previews_without_writing_then_commits_centered_body`（[草图测试](../../../tests/ui/test_part_sketch_workbench.py)、[建模测试](../../../tests/ui/test_modeling_interaction.py)）。几何结果可能相近，但 MyCAD 通过有序命令预览/确认，不是同步方向盘操作。 | [U07 软件渲染区域截图](u07-regions-xvfb.png)及自动测试不构成 ST9 同步操作对照；真实 GPU/人工核对待完成，见 [U07](u07-progress.md)。 |
| V04 同步；00:15、00:35、00:55 | 在模型面/边附近绘线并查看长度、角度反馈。 | MyCAD 可从平面选择启动草图：`test_legacy_selected_planar_face_can_support_new_sketch`；线预览与精确输入分别见 `test_line_preview_matches_inferred_endpoint`、`test_locked_line_dimensions_match_preview_and_committed_geometry`（[零件草图测试](../../../tests/ui/test_part_sketch_workbench.py)）。录像中的同步边缘关联绘线没有被这些测试覆盖。 | 没有模型边关联绘线的 MyCAD 人工对照记录；相关 ST10 草图验收仍待，见 [U04](u04-progress.md)。 |
| V05 同步；00:15、00:45、01:05、01:25 | 草图尺寸、区域选择、除料预览与结果。 | 尺寸映射见 `test_edit_driving_dimension_refreshes_reference_and_downstream`；区域映射见 `test_selected_region_from_sketch_drives_extrude`；MyCAD 的实体差集入口在 `modify.boolean_cut` / [主窗口路由](../../../src/mycad/ui/main_window.py)，当前测试 `test_selected_body_boolean_picks_target_then_tool_and_commits_latest_preview` 覆盖实体差集。它不是 ST9 同步草图除料步骤的等价实现。 | 未留相同对象、尺寸和模式下的人工对照；[U06](u06-progress.md)和[U07](u07-progress.md)将参考与人工验收列为待办。 |
| V06 同步；00:22、00:52、01:07 | YZ 平面圆及直径提示；选圆区域；以实体端点定位并预览圆柱。 | 圆精确值和区域路径由 `test_locked_rectangle_and_circle_dimensions_commit_exact_values`、`test_selected_region_from_sketch_drives_extrude` 覆盖（[测试文件](../../../tests/ui/test_part_sketch_workbench.py)）；MyCAD 没有该 ST9 端点定位的同步关联语义测试。 | 无 ST9 端点定位的 MyCAD 人工对照；[U05](u05-progress.md)/[U07](u07-progress.md)中的自动结果不替代参考操作。 |
| V07 同步；00:22–01:22 | 孔命令条、沉头孔类型/尺寸、端面定位及完成提示。 | MyCAD `feature.hole`/`feature.hole_pattern` 与绑定孔入口分开；测试见 `test_sketch_hole_previews_and_commits_against_selected_planar_face`、`test_hole_pattern_previews_selected_face_and_commits_all_instances` 和绑定孔专项（[建模测试](../../../tests/ui/test_modeling_interaction.py)、[绑定孔测试](../../../tests/ui/test_bound_hole_task.py)）。这些测试不能证明沉头孔或同步定位支持。 | 没有沉头孔和同步定位的 MyCAD 人工对照；U11 参考软件及人工验收仍待。 |
| V08 同步；00:22、00:37、00:52、01:07 | 圆角半径输入/预览；后续显示模型尺寸及方向操作。 | MyCAD 圆角预览/提交见[倒角圆角工具](../../../src/mycad/ui/fillet_toolbar.py)及 `test_fillet_selection_previews_and_commits_one_group`（[测试文件](../../../tests/ui/test_fillet_interaction.py)）。ST9 模型尺寸和方向不是 MyCAD 草图尺寸，也不等于 PMI。 | 圆角测试是软件自动窗口；没有 ST9 实机并列核对。完整 PMI 属 U14，不能以草图尺寸截图替代。 |
| V09 同步；00:22、00:52、01:37、01:52、02:07 | 选面后方向盘/设计意图；拖动模型面并查看尺寸变化。 | MyCAD 没有同步推拉面编辑。`modify.body_transform` 改实体变换；[历史编辑面板](../../../src/mycad/ui/right_panel.py)改已有历史命令参数；两者都不等于同步面移动。几何适配层的 `_extrude_face` 也明示此边界。 | 没有 MyCAD 对应的同步直接面编辑人工证据；完整同步建模尚未排入本轮，见 U14。 |
| V10 Draft；00:10、00:30、00:50、01:10 | 从模型新建工程图、排布投影视图、取回尺寸提示及图纸结果。 | [工程图工作台](../../../src/mycad/ui/drawing_workbench.py)、[投影视图测试](../../../tests/ui/test_drawing_views.py)中的 `test_real_model_projection_is_placed_in_canvas`，并有[输出测试](../../../tests/ui/test_drawing_pdf.py)。ST9 抽帧不证明 MyCAD 全链已匹配。 | [U10 工程图截图](u10-engineering-source.png)是 Xvfb/xcb 软件渲染；来源选择、更新、标注和输出有自动链，但 ST10 Draft 对照及人工验收仍待，见 [U10](u10-baseline.md)。 |
| V11 Draft；00:10、00:25、00:40、00:55 | 从图纸进入同步模型、改面后返回图纸，出现尺寸跟踪提示。 | MyCAD 投影视图更新在[drawing updates](../../../src/mycad/ui/drawing_updates.py)，自动边界见[更新测试](../../../tests/ui/test_drawing_updates.py)与 `test_real_model_projection_is_placed_in_canvas`。该链属于 MyCAD 工程图来源更新，不是同步面修改，也不代表 ST10 Draft 验收。 | 未留 MyCAD/ST9 图纸往返人工对照；[U10](u10-baseline.md)保留引用失效、重选、更新和人工核验余项。 |

## 核对结论与验证边界

1. 当前可确认的模式差异是：ST10 录像前段先展示同步空闲界面，约 00:17 转为有序；目前登记的后续 ST10 草图、尺寸和孔片段主要属于有序环境。ST9 V01–V09 片段是同步课程；V10/V11 是 Draft。版本和模式均按每个本地画面登记，不跨录像推断。
2. 数值输入、区域拉伸、圆孔或圆角的视觉/几何交集只说明值得对照。MyCAD 的自动测试针对自身命令和有序特征链；不能据此声称同步建模、同步关联、方向盘编辑或同步模式切换已实现。
3. 本次核验的 MyCAD 侧是源码/测试与既有虚拟窗口证据映射；没有物理显示器、真实 GPU、完整键鼠比较或用户验收记录。各包的人工作业状态仍以 U04–U07、U10/U11 进度文件为准。
4. V12–V24、ST10 全片和 ST9 各片完整操作链仍未完成逐段核对；U00 保持未完成。

本次验证：`ffprobe` 核对 ST10 与 ST9 V02 的视频尺寸/时长；`sha256sum` 重核 ST10、ST9 V02/V03/V09 源文件；`ffmpeg` 重取 ST10 本地 00:17、ST9 V03 00:40、V09 00:52 帧并目视核对标题/模式和操作。仅更新文档证据，未运行代码测试。

2026-11-07 后续：用户另提供 Draft 视频目录，其中 01、02、04、06 号画面标题可确认 ST10 Draft；01 号已建立图纸/视图/标注/过期警告的选段与 MyCAD 映射，见 [ST10 Draft 观察](st10-draft-video-reference/observations.md)。上文“ST10 本地录屏只取到同步空闲/模式切换”等结论限定于原 `solidedge_st10_01.mp4`，不覆盖新目录。录像选段与同条件实机对照、用户验收分开计状态。
