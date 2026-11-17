# U00 独立二维动作与入口盘点

日期：2026-11-07。范围为当前工作区 `SketchEditorDialog(select_committed_entities=True)` 的独立二维文档；零件草图和工程图另行盘点。依据是源码和已有测试记录，按钮存在或信号已连接不等于完整功能、参考软件对照或用户验收通过。当前工作区有未提交改动，本表不是提交 `404b5a3` 的干净版本清单。

## 绘图及修改

工具栏的选择、绘图和局部编辑按钮设置 `tool_combo`，再由画布工具状态处理；命令栏仅在独立二维的 `select_committed_entities=True` 模式显示。具体对象、图层和候选有效性还由画布处理，不能只凭按钮启用判断操作可提交。

| 动作身份 | 入口及处理 | 可用条件和边界 | 工程证据入口 |
| --- | --- | --- | --- |
| 选择元素 | 绘图栏、工具选择框；画布选择及图形导航 | 已保存与草稿的选择由画布状态和图层可见性控制；隐藏、锁定图层的行为需按具体操作区分。 | [草图编辑测试](../../../tests/ui/test_sketch_editor.py)、[已保存图元测试](../../../tests/ui/test_saved_drawing_selection.py) |
| 直线 `L`/`LINE`、多段线 `PL`/`PLINE` | 绘图栏、工具选择框、二维命令栏；画布收点 | 连线完成和取消由画布状态处理；坐标、捕捉、动态输入分别核对，不能仅以别名存在推定完整 AutoCAD 命令。 | [命令栏测试](../../../tests/ui/test_drawing2d_command_bar.py)：`test_command_line_drives_canvas_with_absolute_and_relative_points`、`test_command_options_close_polyline_and_undo_last_line_segment` |
| 矩形 `REC`/`RECTANGLE`、多边形 `POL`/`POLYGON` | 绘图栏、工具选择框、二维命令栏 | 多边形参数有边数和内接/外切选择；动态尺寸仅覆盖直线、矩形、圆。 | `test_polygon_command_uses_current_polygon_options`；[动态输入测试](../../../tests/ui/test_drawing2d_dynamic_input.py) |
| 圆 `C`/`CIRCLE`、圆弧 `A`/`ARC`、样条 `SPL`/`SPLINE` | 绘图栏、工具选择框、二维命令栏 | 圆提供半径或 `D` 直径；录像中的两切点加半径 TTR 尚无等价圆命令。样条为至少四控制点的三次 B 样条；不据此宣称其修剪/延伸/偏移受支持。 | `test_circle_command_accepts_diameter_or_radius`；参考差异见 [AutoCAD 录像观察](autocad-video-reference/observations.md) |
| 修剪 `TR`/`TRIM`、延伸 `EX`/`EXTEND`、分割 | 修改栏和工具选择框；修剪/延伸也有命令栏入口 | `C` 可选择显式边界，空选择确认使用可见边界；草稿和已保存目标受图层、来源修订和几何类型限制。分割不是完整 BREAK/BREAKATPOINT；样条及 AutoCAD 全部模式未覆盖。 | `test_trim_command_selects_explicit_boundary`、`test_extend_command_uses_selected_boundary`；更多范围见[二维进度](u09-progress.md) |
| 二维圆角 `F`/`FILLET` | 独立二维修改栏和命令栏；`R` 设置半径 | 当前限两圆间保留源圆的外切圆弧，不修剪源圆、不建立相切约束；其他对象组合和选项不能视为已实现。 | [二维修改审计](../../../docs/design/2026-11-04-autocad-2d-modify-audit.md)、[二维进度](u09-progress.md) |
| 移动 `M`/`MOVE`、复制 `CO`/`COPY` | 修改栏、数值参数页和命令栏，共用画布变换状态 | 支持草稿、可见已保存对象及混选的相应路径；复制支持连续放置及部分命令选项。锁定图层、失效来源和约束可阻止提交。 | `test_move_command_uses_preselection_and_relative_coordinates`、`test_copy_array_command_spacing_fit_and_undo`；[已保存图元测试](../../../tests/ui/test_saved_drawing_selection.py) |
| 旋转 `RO`/`ROTATE`、镜像 `MI`/`MIRROR` | 修改栏、数值参数页和命令栏 | 旋转支持数值参考角及部分参考点路径，任意两点参考线和 Copy 选项仍缺；命令栏镜像会询问是否删除源对象，参数页另有保留源偏好。 | `test_rotate_reference_numeric_angles`、`test_mirror_command_asks_before_erasing_source`；[二维进度](u09-progress.md) |
| 数值偏移与侧向偏移 `O`/`OFFSET` | 数值偏移由修改栏及参数页 `_apply_transform` 处理；侧向偏移由独立按钮与命令栏 `start_offset` 共用状态 | 两个入口都是偏移但交互不同：前者先选择并设置数值；后者输入距离后选对象、选侧并可连续生成。侧向偏移限支持的线、圆、弧及无歧义多段线；点、样条不支持，退化或来源失效会拒绝。 | [偏移计算](../../../src/mycad/ui/drawing_offset.py)；`test_offset_command_distance_side_repeat_and_escape`、`test_interactive_offset_button_shares_command_and_repeat` |
| 线性/环形阵列 | 修改栏与数值参数页 `_apply_transform` | 需要选择对象，生成独立副本；当前线阵为单方向步距，不能据此宣称关联、二维行列或路径阵列已完成。COPY 中的 Array 是另一命令步骤。 | [二维修改审计](../../../docs/design/2026-11-04-autocad-2d-modify-audit.md)、[已保存图元测试](../../../tests/ui/test_saved_drawing_selection.py) |
| 删除 `E`/`ERASE` | 键盘 Delete、命令栏；画布 `delete_selected` | 草稿、已保存及混选有各自处理；锁定图层、依赖约束和来源修订等可能拒绝。 | `test_erase_command_deletes_selected_draft_geometry`、`test_erase_command_deletes_saved_object_and_can_undo` |

工具栏变换按钮在没有未完成图元和活动编辑手势时刷新启用状态：移动、复制、旋转、镜像允许进入选择流程；数值偏移和阵列还要求选择工具及已有选择。侧向偏移按钮为独立入口，不应与数值偏移重复计为两个不同几何能力。具体守卫见 [SketchEditorDialog](../../../src/mycad/ui/sketch_editor.py) 的 `_start_transform`、`_sync` 相关逻辑及 [Drawing2DCommandBar](../../../src/mycad/ui/drawing2d_command_bar.py)。

## 尺寸、图层与状态控件

| 动作或身份 | 入口及处理 | 状态与证据边界 |
| --- | --- | --- |
| 智能、水平、垂直、对齐、角度、半径、直径、弧长、连续、基线、坐标 | 尺寸工具栏由 [DimensionTools](../../../src/mycad/ui/dimension_tools.py) 的 `COMMANDS` 创建按钮并调用 `start`；有标注层、画布输入及确认/取消控件。 | 按钮提示中的 `DIM*` 文本不证明二维命令栏能解析这些命令。默认勾选驱动尺寸，可切换参考尺寸；普通标注与参数化标注的产品语义、旧档兼容仍需 U09 专项确认。参考[画布尺寸测试](../../../tests/ui/test_canvas_dimensions.py)与[驱动尺寸测试](../../../tests/ui/test_driving_dimensions.py)，不以测试名表示整组验收通过。 |
| 图层管理、当前层、标注层 | 图层管理按钮和二维图层面板；尺寸工具栏另有标注层选择 | 源码声明显示、冻结、锁定、颜色、线型和线宽；已保存对象与草稿、选择及尺寸联动需按具体操作复验。参考 `test_layer_manager_styles_layer_and_editor_records_new_geometry_on_it` 等[草图测试](../../../tests/ui/test_sketch_editor.py)。 |
| 网格 F7、对象捕捉 F3、正交 F8、栅格捕捉 F9、动态输入 F12 | 二维状态控件和快捷键；在独立二维模式启用额外快捷键 | 网格显示与栅格捕捉分开；动态尺寸仅直线、矩形、圆。极轴追踪不能由正交或捕捉控件推定已实现。真实中文输入法组合态与物理键盘仍待人工验证。 |
| 完成/取消、图元撤销/重做、工具栏与面板、三维视图 | 绘图栏、参数页、工具栏菜单及图层栏 | 完成草图需有图元或混合暂存，且无未完成图元或活动手势；图元撤销/重做依草稿和图层历史。三维视图入口切换已提交模型视图，不能把它当作新建零件。文档生命周期与跨环境行为另属 U01/U02。 |

## 不覆盖和核验方式

- 本表是独立二维的动作清单；公共动作目录、插件运行时贡献、零件草图及工程图需分别完成盘点。本表没有动态加载用户插件。
- 实现范围、自动测试、参考软件核对、用户验收分开记录。已知更多对象、选项、DXF 往返及实机输入问题见 [U09 进度](u09-progress.md)和[二维验收基线](../../../docs/design/autocad-2d-interaction-acceptance.md)；未逐条手工复现的动作均保留待验。
- 本次只进行源码与既有测试名称核对，没有执行代码测试。工作区源码 SHA-256：`sketch_editor.py` `1c758e768eab000cd21c278c270b016974c7db5b2486326c6925c1bdaf5a140f`；`drawing2d_command_bar.py` `219b75757db6f4dd4bc65a6f8e724c1c77b692c92f829167200523e62f9a89c5`；`drawing_offset.py` `c31544a1bdd5c18982999638c936aa0b158585a63dae698350a484764b984b60`；`dimension_tools.py` `ba13e865af51b7e7019686e200cdbfd41cc45548104f890a7735c3c1b3689597`。后续修改时应重新核对。


## 2026-11-07 后续实现修订

上表为盘点时快照。此后 ROTATE 的 R 参考角支持由任意两点确定参考线，C/COPY 支持保留来源并旋转副本；FILLET 新增两条相交有限直线的修剪圆角。草稿、已保存对象及混选、撤销和保存重开已有自动测试；线与圆/圆弧、延长不相交直线、自动相切约束及完整参考操作仍未覆盖。最新实现和验证范围以 [U09 进度](u09-progress.md)为准；上方哈希仍是原盘点快照。
