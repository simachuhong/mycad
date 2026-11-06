# U06 工程与验证记录（2026-11-05）

状态：工程实现和自动验证进行中；ST10 实机、物理 GPU 与用户验收待核对，不以截图或自动测试代替。

- 草稿尺寸支持长度、距离、角度、半径和直径的画布拾取及放置，使用现有约束求解对话框；驱动和参考分别显示，尺寸位置与约束 ID 保存。矩形和多段线边可作为长度/角度引用。
- 草稿尺寸与关系按稳定 ID 拾取，重叠标注可轮流选择；关系可删除并本地撤销。双击驱动尺寸在视口中编辑；冲突保留有效草稿并提示关联 ID，分支变更转入原有确认流程。参考尺寸为只读。
- 下游候选需预览并明确接受；画布修改半径后验证参考直径及拉伸体积更新、Bus 撤销以及保存重开。来源改变时编辑器失效，求解器忙时禁止执行。
- scoped 回归：`tests/ui/test_part_sketch_workbench.py tests/ui/test_part_sketch_dimensions.py tests/ui/test_sketch_dynamic_input.py tests/ui/test_sketch_constraint_dialog.py tests/ui/test_viewport.py tests/test_layering.py tests/geom/test_m2b_associated_constraints.py`：150 passed，1 skipped（offscreen 无 OpenGL framebuffer；执行时为本次测试增强前的版本）。
- Xvfb + xcb + 200% 缩放：尺寸创建、重叠选择、驱动尺寸编辑与下游保存重开等 8 passed；物理 GPU 未验证。`u06-draft-dimensions-xvfb.png` 为软件环境草稿尺寸截图，并非 ST10 对照或用户验收。
- 分支变化和冲突反馈的界面分支使用受控求解结果测试；完整实际复杂冲突场景仍需人工与进一步回归。真实 ST10 画布放置、自由度表达和视觉差异待核对。
- 2026-11-06 零件草图全套在 200% 缩放下首次复验为 114 通过、1 失败：尺寸编辑忙碌提示被通用等待提示覆盖，模型与草稿未发生错误修改。统一提示明确说明应用忙碌后，全套复跑 115 项通过；相关源码 Ruff、格式与严格类型检查通过。

本次记录的源码 SHA-256：

- `part_sketch_workbench.py`：`68476574e0500e296afa76563f8e00148b4c8c9106bb6f86cd70b7247110f99a`
- `part_sketch_dimensions.py`：`50788ffbc446e6d1dff7f26c7451a8160bcf0bc46a140bb7094a9ee5ddefb7a5`
- `viewport.py`：`e476ecc9bfe20ebe559c4f3316cc441a9dccf7a3d6e947f6df74630d89350d18`
- `sketch_constraint_dialog.py`：`d00f348d061c9c3460fa8253763012dad70b8dc696a4c48466a605c9acf8ce1e`
