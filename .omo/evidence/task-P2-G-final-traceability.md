# P2 G 最终条款与交互门槛映射

最新状态：第二轮六项人工反馈及新建文件类型入口已整改，证据和范围见 [第二轮整改](task-P2-G-drafting-round2.md)。草稿图层编辑不等于全局已提交图层管理；用户复验仍未通过。

2026-10-25 人工验收更新：二维工作区/UCS/工具面板/连续闭合交互四项不通过，本轮整改已完成、待复验；下文保留的是此前工程证据，不能解释为当前二维验收通过。

2026-10-25。此前状态：工程实现与自检完成；最终独立审查五项 Important 已修复，240 项组合回归通过；全量及随后增量处置见 `task-P2-G-final-integration.md`。此表汇总当前实现和已完成定向证据；不代表用户人工验收通过。

## 原计划条款

| 任务 | 实现与证据入口 | 任务级检验 | 明确边界/最终待查 |
| --- | --- | --- | --- |
| P2-32 基础二维图元、平面、身份、输入、捕捉、轮廓 | `core/sketch.py`、`ui/sketch_editor.py`、`geom/sketch_profiles.py`；`tests/core/test_sketch.py`、`tests/geom/test_sketch_commands.py`、`tests/ui/test_sketch_editor.py`；独立 drawing2d 证据、profile-diagnostics 证据 | 法兰、阶梯轴、带弧/长圆孔板由空白 GUI 画出；XY/XZ/YZ 映射、弧方向、内外环、开口/交叉/退化定位、保存重开与身份 | 直接画布编辑限未提交草稿（用户已选择）；图元错误为文字/局部坐标定位，不宣称全部有交点高亮 |
| P2-33 关系/尺寸、求解器/容差/重放、DOF/冲突/分支 | ADR-010；`geom/sketch_constraints.py`、`geom/sketch_branches.py`、`ui/sketch_constraint_dialog.py`；`tests/geom/test_sketch_constraints.py`、`tests/core/test_sketch_constraints.py`、`tests/geom/test_sketch_branches.py`；branch-feedback、conflict-location 证据 | 草稿约束拖动/撤销，水平/竖直冲突定位→改有效长度→确认；已有半径修改驱动法兰实体；失败不提交部分解，存档使用冻结结果而不重新求解 | 首批受限 PlaneGCS 子集；分支检查保守，不把零 DOF 当作唯一解证明；用户实机操作待验收 |
| P2-34 修剪/延伸/分割/偏移、变换/阵列、捕捉/引用 | `core/sketch_edit.py`、`ui/sketch_editor.py`；`tests/core/test_sketch_edit.py`、`tests/ui/test_sketch_editor.py`；既有曲线/开放折线系列证据和 offset-path-guards | 带弧板、长圆孔、等距孔系；拖动修剪按手势撤销/取消；偏移自交/交叠/短边/反向/非唯一转角；用户约束引用不静默转接，完整草稿 undo/redo | 闭合路径/矩形跨起点/非跨起点修剪分割已有8种成功路径、长度和身份回归；复杂偏移拓扑不自动修复，失败明确拒绝；整圆延伸不适用 |
| P2-35 图层/尺寸/DXF | `core/sketch_layers.py`、`formats/providers/dxf_provider.py`、`formats/dxf_preview.py`、`ui/dxf_output_preview.py`；DXF exchange/output-preview 测试与证据 | 五类原生 DIMENSION，单位/精度/比例/驱动参考，图层显隐锁定（含间接求解保护），闭合弧与单位往返，未知单位明确输入，不支持项报告；实际字节预览→确认原子写入 | R2010 支持子集；带 bulge/宽度的 LWPOLYLINE 明确跳过并报告；无 MyCAD XDATA 的外部尺寸不能伪装成关联可编辑尺寸；目标 AutoCAD/Solid Edge 实机显示/字体核对由用户人工执行 |
| P2-36 草图拉伸/旋转/孔/阵列/重建 | `geom/_b123_features.py`、`geom/kernel.py`、`ui/modeling_toolbar.py`、`ui/main_window.py`；sketch extrusion/hole 与 modeling interaction 测试；consumer-rebuild、existing-dimension-update、part-workflows 证据 | 法兰/阶梯轴/长圆孔安装板从 GUI 建模→修改→undo/redo→存档/STEP；对称/到面、孔贯穿/盲深；过大孔/错轮廓恢复；法兰孔径/数量历史改参 | 不支持的终止条件应明确拒绝/禁用；平面推拉不等于完整同步面编辑；版本1/2旧命令语义保持 |
| P2-37 多边修改、多实体布尔/变换/通用阵列 | `geom/_b123_features.py`、`geom/body_provenance.py`、`ui/body_display.py`、`ui/right_panel.py`；body operations/provenance、body tree、P2-37 workflows 测试；三份 body evidence 与 task-workflows | 半支架→复制→镜像→并集→两边圆角/倒角；工具保留/消耗与显隐；无关体保留；线性/全圆/部分圆周阵列改数量→undo/redo→重开/STEP；实体来源/输入与历史预览可对应 | 单零件内多实体，非装配求解；显示身份运行时重建，存档选择器歧义/过期拒绝；来源为操作输入关系，不宣称逐面归属 |

## Solid Edge 共同门槛 1～6

| 门槛 | 当前具体证据路径 | 人工核对 |
| --- | --- | --- |
| 1 候选/选择可辨、可纠正、无静默默认 | `tests/ui/test_picking.py` 预选/过滤/框选/循环候选、body tree 选择同步、`test_face_can_be_picked_from_committed_model_during_candidate_preview`、P2-37 实体角色/来源 | 小面/重叠对象选择，隐藏体不误选，目标/刀具顺序清晰 |
| 2 参数不遮模型、操作中导航/继续选 | `tests/ui/test_modeling_toolbar.py::test_narrow_command_bar_keeps_confirmation_visible`、`tests/ui/test_navigation_contract.py`、fillet/modeling interaction | 用户屏幕缩放下参数条、应用/取消可达；中键旋转、Shift+中键平移、滚轮缩放 |
| 3 当前相关参数、方向/尺寸、预览与相机 | `test_profile_and_tool_switches_serialize_only_active_schema_branch`、模型面/XY来源分离、对称/到面参数；坐标31项和综合88项证据 | 正负方向/非XY面、预览中导航与修改参数无跳动；XYZ 角标与真实相机一致 |
| 4 缺目标/错误选择明确阻止 | `test_extrude_requires_face_and_previews_the_whole_face`、草图源要求、错误轮廓恢复、缺边/体禁用确认 | 空白点击不会创建无关几何，曲面与不适用终止条件有说明 |
| 5 最新有效预览、一次提交、失败纠错/取消/重放 | async preview generation tests、constraint conflict/rebuild tests、body visibility busy/preview tests、part/P2-37 workflows、DXF source-stale/atomic tests | 快速改值/取消/切文档无旧结果残留；失败保留输入；undo/redo/重开一致 |
| 6 右键/Enter 分步骤与输入焦点 | `test_first_right_click_accepts_handle_second_commits_once`、fillet toolbar accepting-radius-not-commit、navigation contract | 文本框 Enter 只接受输入，图形区后续确认；右键接受/完成不同时旋转或弹窗 |

## 证据判定

定向测试、真实 XCB 自检截图与用户人工验收分开。全新 Astra reviewer 的5项 Important 已红绿修复；全量静态三门通过，pytest1678通过/2失败，修复后相关160项通过；按增量纪律未重复整套。审查与处置分别见 `task-P2-G-final-review.md` / `task-P2-G-final-review-fixes.md`。此前各里程碑和历史“尚未实现”文字不可独立作为当前完整状态判定。
