# GROUP / BLOCK 实施证据索引

状态：**开发与定向验证持续中，人工验收待执行**。本索引用于定位证据，不是全量测试报告，也不表示表中每一项的所有边界均已验收。实际执行命令、结果和后续修复以 [进度记录](../../.omo/start-work/drawing-groups-blocks-progress.md) 为准；用户操作、样图和人工结果表见 [人工验收清单](2026-11-21-drawing-collections-manual-check.md)。

交接要求逐项映射、当前证据及未证明项见[交付核对](2026-11-22-drawing-collections-completion-audit.md)。

| 计划任务 | 当前可检查的主要实现和定向证据 | 仍需关注 |
|---|---|---|
| G0 引用与映射 | [组模型](../../src/mycad/core/drawing_groups.py)、[引用与成员映射](../../src/mycad/core/drawing_object_refs.py)；[组模型测试](../../tests/core/test_drawing_groups.py)覆盖输入冻结、直接组选择、完整复制及一对多映射 | 结合具体编辑命令检查对象替换时的身份映射；不能据此推断所有编辑命令均已覆盖。 |
| G1 持久状态与 batch | [命令 Bus](../../src/mycad/core/bus.py)、[命令注册](../../src/mycad/builtin_commands/drawing_group_specs.py)；[事务测试](../../tests/app/test_drawing_object_batches.py)含失败回滚、重开一次撤销及 v7 显式升级；[块命令测试](../../tests/app/test_drawing_block_commands.py)含优化重建 | 外部软件和旧程序对新命令的实际行为仍需对应环境验证。 |
| G2 共同时间线 | [会话实现](../../src/mycad/ui/drawing_collection_session.py)；[联合时间线测试](../../tests/app/test_drawing_collection_timeline.py)含取消、提交、重开及逐步撤销重做 | 联合自动测试通过应用接口执行；进入 BEDIT 前按规则先完成草稿，真实桌面流程待人工检查。 |
| G3 GROUP 闭环 | [组管理界面](../../src/mycad/ui/drawing_collections.py)、[主窗口接入](../../src/mycad/ui/main_window.py)；[画布会话测试](../../tests/ui/test_drawing_collection_session.py)含命令、重叠组、组选择与混合操作；[剪贴板测试](../../tests/app/test_drawing_collection_clipboard.py) | 混合标注、图片、锁层及重叠组仍须按人工清单复核；公差工作包的人工结果单独记录。 |
| B0 领域展开 | [块模型](../../src/mycad/core/drawing_blocks.py)、[领域测试](../../tests/core/test_drawing_blocks.py) | 位置、曲线、文字、比例和图层继承的自动断言不能代替参考软件外观对照。 |
| B1 创建、插入与捕捉 | [块事务](../../src/mycad/core/drawing_block_transactions.py)、[块工具](../../src/mycad/ui/drawing_block_tools.py)；[块命令测试](../../tests/app/test_drawing_block_commands.py)、[画布测试](../../tests/ui/test_drawing_block_tools.py)、[入口测试](../../tests/ui/test_drawing_block_commands.py) | 实际桌面点取、图层、捕捉及不建立外部持久关联需人工检查。 |
| B2 编辑、分解与剪贴板 | [局部编辑会话](../../src/mycad/ui/drawing_block_editor.py)、[编辑器测试](../../tests/ui/test_drawing_block_editor.py)；[块命令测试](../../tests/app/test_drawing_block_commands.py)含分解重开和失败边界，[跨文档剪贴板测试](../../tests/app/test_drawing_collection_clipboard.py)含定义冲突与样式 | 人工确认 BSAVE/BCLOSE、失效/锁层提示、共享更新、分解外观及跨文档复制。 |
| X0 DXF | [DXF 读写](../../src/mycad/formats/providers/dxf_provider.py)、[handle 映射](../../src/mycad/formats/dxf_collections.py)；[交换测试](../../tests/formats/test_dxf_collections.py)、[导入界面测试](../../tests/ui/test_dxf_collection_import.py) | AutoCAD 2023 和 2025 的原生往返、外部修改及损失报告均待各版本实际执行。裁剪和外观覆盖等明确不支持项应按清单检查报告。 |

## 补充的身份和联合操作证据

- [组命令测试](../../tests/app/test_drawing_collection_commands.py)的 `test_group_create_rejects_uuid_alias_without_rewriting_existing_id` 检查 UUID 不同写法的碰撞、失败回滚、原身份保存重开及撤销/重做。[组复制测试](../../tests/core/test_drawing_groups.py)另检查副本身份、完整/部分复制和重叠组。
- [用户界面联合测试](../../tests/ui/test_drawing_collection_workflow.py)的 `test_numeric_group_copy_from_dimension_seed_preserves_association` 检查数值复制从尺寸种子扩展整个组、副本尺寸引用新几何及保存重开后的撤销/重做；重叠组和关闭组选择的部分复制另有定向测试。
- 同一文件的 `test_numeric_group_move_translates_attached_datum_and_block_once` 检查数值移动时附着基准只跟随一次、块实例同步移动及重开撤销。
- [块编辑器测试](../../tests/ui/test_drawing_block_editor.py)的 `test_block_editor_retains_local_edits_after_instance_layer_changes` 检查两实例共享定义编辑时另一实例层被锁定，BSAVE 拒绝并保留局部修改，以及放弃后的保存重开。
- [块命令测试](../../tests/app/test_drawing_block_commands.py)的 `test_grouped_explode_with_text_survives_optimized_rebuild_and_reopen` 检查组内块分解的几何、文字和身份映射在后续优化重建及重开逐步撤销中保持一致。
- [块命令界面测试](../../tests/ui/test_drawing_block_commands.py)的 `test_block_conversion_attached_group_fails_without_changing_draft_then_can_keep_sources` 检查带外部基准附着的混合已保存/草稿组不能转块，失败后可保留源对象创建定义，并验证重开撤销/重做。
- [事务测试](../../tests/app/test_drawing_object_batches.py)的 `test_unmapped_group_replacement_emits_committed_warning_and_undoes` 覆盖直接修订与复合命令提交后的未映射成员报告、失败回滚和重开撤销；[组会话测试](../../tests/ui/test_drawing_collection_session.py)覆盖暂存提示及直接命令的状态栏显示。未明确映射的替代关系不会被推断。
- 同一事务测试文件的 `test_v7_collection_batch_requires_candidate_upgrade_and_preserves_audit` 对照实际升级前后 JSON 顶层字段、`named_groups`、命令审计字段及重开撤销。
- 同一事务测试文件的 `test_batch_children_keep_versions_and_context_through_failure_and_replay` 检查 batch 子命令版本及父身份、失败回滚后的后续修订和重开重放上下文。
- [事务测试](../../tests/app/test_drawing_object_batches.py)的 `test_candidate_commit_reports_unmapped_group_replacement_only_after_success` 覆盖候选预览隔离、成功事件顺序及重放或最终校验失败后的回滚；`test_candidate_reports_unmapped_group_created_in_earlier_staged_step` 覆盖同一候选先建组再修订、最终步骤保留整次提交的报告及重开后的逐步撤销。重叠组的部分映射报告由 `test_partial_mapping_of_overlapping_groups_reports_unmapped_membership` 覆盖。
- [块命令测试](../../tests/app/test_drawing_block_commands.py)的 `test_block_rejects_uuid_alias_without_rewriting_existing_identity` 分别检查定义和实例身份碰撞，保留原始引用，并验证保存重开及撤销/重做。共享更新和优化重建由该文件中其他定向测试覆盖。
- [块命令测试](../../tests/app/test_drawing_block_commands.py)的 `test_attached_mixed_group_move_rejects_restricted_member_layer_atomically` 检查含附着基准、图片和块实例的混合组在图片或实例层锁定、隐藏或冻结时整体拒绝，解除限制后成员各移动一次，并验证重开撤销/重做。
- [DXF 导入测试](../../tests/app/test_dxf_collection_import.py)的 `test_import_grouped_block_on_new_restricted_layer_preserves_state` 和 `test_repeated_dxf_import_remaps_restricted_layers_for_all_group_members` 检查受限图层导入、失败回滚、重复导入的混合组身份和图层、保存重开撤销；[导入界面测试](../../tests/ui/test_dxf_collection_import.py)检查预览中的图层改名报告和一次撤销。AutoCAD 人工结果仍待执行。
- [DXF 交换测试](../../tests/formats/test_dxf_collections.py)的 `test_native_block_and_group_edits_override_old_metadata_together` 同时检查外部修改块定义、实例位置和组成员后，导入使用当前原生内容。
- [DXF 导入事务测试](../../tests/app/test_dxf_collection_import.py)的 `test_external_native_edits_reimport_without_overwriting_existing_blocks` 在目标已有同名定义时重复导入上述原生修改，检查身份及引用重映射、原定义不变和重开逐次撤销。
- [DXF 格式测试](../../tests/formats/test_dxf_collections.py)的 `test_cyclic_external_blocks_are_rejected_without_partial_group_import` 与[导入界面测试](../../tests/ui/test_dxf_collection_import.py)的 `test_dxf_preview_reports_cyclic_blocks_and_imports_only_valid_group_member` 检查循环嵌套块被整体拒绝、有效组成员继续导入、确认前报告及重开撤销。
- 同一交换测试文件的 `test_external_unicode_casefold_collisions_keep_distinct_blocks_and_groups` 检查外部块及组名称在目标文档判重规则下冲突时的独立映射、改名报告、重复导入与重开撤销；未引用块定义的同类冲突另有定向测试。
- `test_external_block_member_layer_casefold_collisions_keep_distinct_layers` 检查相同判重冲突的图层对块、实例及普通几何/文字的映射；[导入界面测试](../../tests/ui/test_dxf_collection_import.py)检查块、组及图层的改名报告在确认前可见。
- `test_native_annotation_layers_follow_casefold_collision_mapping` 检查冲突图层下公差框、基准和独立参考尺寸的组导入及撤销；`test_associated_dimension_uses_modified_native_layer_with_casefold_collision` 检查关联尺寸采用外部修改后的原生图层。
- `test_external_text_style_casefold_collisions_preserve_block_and_model_fonts` 与 `test_external_font_name_conflicts_across_separate_blocks_are_reported` 检查外部文字样式名称冲突时块内及模型空间字体保留与改名报告。
- `test_external_nearly_uniform_block_scale_is_not_silently_changed` 检查接近但不相等的实例比例被拒绝且组成员损失被报告；[导入界面测试](../../tests/ui/test_dxf_collection_import.py)的 `test_dxf_preview_reports_nearly_uniform_instance_and_imports_valid_group` 检查确认前报告、有效实例导入及重开撤销。
- `test_external_block_with_small_out_of_plane_normal_is_not_flattened` 检查实例及块内成员的轻微倾斜不会被静默投影；`test_dxf_preview_reports_slightly_tilted_instance_and_incomplete_group` 检查真实导入预览、部分组报告和撤销。
- `test_external_block_rejects_slightly_out_of_plane_mtext_direction` 检查多行文字方向的轻微离面不会被静默投影；非零极小平面方向、导入预览与撤销另有定向测试。
- `test_external_block_coplanar_with_nonzero_base_height_is_flat_after_insertion` 检查块成员与非零高度基点共面时的归一化；离面成员及实例拒绝、实际预览与重开撤销由对应定向测试覆盖。
- `test_external_block_with_compensated_height_is_in_drawing_plane` 检查成员平面与基点高度不同但插入变换将其放回图纸平面，以及共享定义中离面实例的单独报告；`test_nonzero_base_plane_block_units_transform_and_dxf_roundtrip` 检查单位、变换及实际预览字节往返。
- `test_external_plane_preflight_manual_sample_preview` 使用人工清单中的无元数据样图，核对确认前报告、两个有效实例及部分组导入和撤销；这不代替参考软件人工验证。
- `test_external_block_accepts_positive_nonunit_xy_normal` 检查实例及块内圆、多段线、椭圆、单行和多行文字的正向非单位 XY 法向、坐标及原生 DXF 往返；倾斜和反向法向仍拒绝。`test_dxf_preview_imports_nonunit_normal_and_reports_tilted_instance` 使用人工清单样图检查真实导入预览、部分组和重开撤销，参考软件人工结果待记录。
- `test_legacy_polyline_block_inch_transform_explode_and_group` 检查传统二维多段线块的英寸转换、旋转缩放、分解及组引用和重开撤销；`test_legacy_polyline_manual_sample_preview` 使用人工清单中的无元数据样图，检查有效实例、不支持宽度的报告及撤销。参考软件人工结果仍待执行。
- `test_repeated_legacy_polyline_import_remaps_group_and_curve_identities` 检查该样图重复导入的名称冲突、块实例、组成员和曲线点身份，以及保存重开后的撤销和重做。
- `test_external_group_includes_modelspace_legacy_polyline` 检查模型空间传统二维多段线的原生 GROUP 成员映射、导出字节及重开撤销；`test_modelspace_legacy_group_preview_reports_only_invalid_member` 检查无法表示成员的预览报告和有效成员导入。
- `test_modelspace_legacy_group_manual_sample_preview` 对人工清单中的模型空间样图检查确认前损失报告、有效组成员及一次撤销；参考软件结果仍待执行。
- `test_external_block_rejects_subtle_unrepresentable_spline` 检查块内权重或节点微小偏差不会被静默替换，`test_external_uniform_spline_block_preserves_supported_control_points` 检查支持的均匀样条；界面测试另检查预览报告和撤销。
- `test_spline_block_and_group_survive_actual_dxf_preview_roundtrip` 检查多种控制点数量的样条块经实际预览字节导回及组映射；等正权重可无损归一化，非等或非正权重的拒绝有对应定向测试。
- `test_external_nearly_closed_ellipse_block_keeps_its_arc_gap` 检查近闭合椭圆弧不会被变成完整椭圆；`test_ellipse_block_preview_roundtrip_preserves_open_or_closed_sweep` 检查完整及近闭合、正负方向的实际输出字节；外部非零起点完整椭圆与超一圈参数另有定向测试。
- `test_external_short_ellipse_arc_block_is_not_treated_as_empty` 与 `test_short_ellipse_arc_block_roundtrips_actual_preview_bytes` 检查大半径短弧的导入、正负方向及组映射；零角度和模型精度外角度单独验证拒绝。
- `test_unicode_conflict_sample_roundtrips_through_actual_preview_bytes` 检查 Unicode 样图导入后再次导出的实际预览字节，以及导回后两个组、实例、非 0 层几何和字体的对应关系。
- `test_last_instance_removed_definition_survives_preview_export_and_reimport` 检查最后实例删除后，非 0 层几何和文字定义在保存重开及实际 DXF 预览字节中保留，并可导回和撤销删除。
- `test_grouped_block_layer_inheritance_survives_explode_and_dxf_exchange` 检查组内旋转缩放块分解前后的图层继承、实际预览导回、组成员替换和重开撤销。
- `test_exploded_overlapping_groups_keep_direct_selection_and_dxf_mapping` 检查重叠组共享块分解后的成员映射、导回后的单层选择扩展及重开撤销/重做。
- [块命令测试](../../tests/app/test_drawing_block_commands.py)的 `test_convert_overlapping_groups_requires_identical_memberships_and_roundtrips` 检查重叠组成员归属不一致时转块拒绝，以及归属一致时两组替换为同一实例、重开撤销和 DXF 导回。
- 同一文件的 `test_convert_coplanar_sketches_projects_to_one_block_and_reopens` 检查不同共面草图轴下的组转块、基点和展开坐标、重开撤销与 DXF 导回。
- `test_keep_array_geometry_creates_independent_block_without_changing_array` 与 [窗口测试](../../tests/ui/test_drawing_block_commands.py)的 `test_block_keep_array_geometry_from_command_bar` 检查保留阵列来源或成员的当前几何、原阵列不变和转块拒绝。
- `test_keep_geometry_with_constraints_tangency_and_attached_datum` 检查同时具有尺寸、跨草图相切和基准附着的源几何，在保留源方式下生成独立块定义并保持原关联。
- [块入口窗口测试](../../tests/ui/test_drawing_block_commands.py)的 `test_block_command_converts_group_from_coplanar_sketches` 检查点选、组扩展、BLOCK 命令及提交重开。
- [跨文档剪贴板测试](../../tests/app/test_drawing_collection_clipboard.py)的 `test_cross_document_block_paste_matches_uuid_alias_and_content` 检查同一块定义 UUID 的不同合法写法、内容一致时共享定义、内容冲突时重映射，以及完整组成员引用和重开撤销；损坏载荷中的重复定义及实例身份由同文件的校验测试覆盖。
- 同一测试文件的 `test_same_identity_block_reuse_requires_matching_text_style_content` 检查定义及样式 ID 均相同时，样式内容变化会触发定义重映射，并保留源字体设置及目标样式。
- `test_group_clipboard_rebinds_attached_annotations_across_documents` 检查由块实例种子跨文档复制附着标注、图片和块的混合组，以及提交、撤销和图片缺失的 DXF 报告。
- [混合对象窗口测试](../../tests/ui/test_drawing_block_commands.py)的 `test_full_mixed_group_cross_document_clipboard_from_block_seed` 另通过真实窗口检查附着基准、公差框、关联尺寸、图片和块的移动、预览、跨文档粘贴、DXF 导回与重复导入后的组内关联。
- [块编辑测试](../../tests/ui/test_drawing_block_editor.py)的 `test_cross_document_block_edit_updates_only_destination_definition` 检查跨文档复用或重映射定义后的编辑隔离、重开撤销及过期会话保护。
- 同一测试文件的 `test_block_editor_rejects_excluded_commands_and_keeps_drawing_local` 检查块编辑中的自动约束禁用、排除命令拒绝、主文档写入隔离及共享保存和重开撤销。
- `test_block_edit_remains_available_when_new_main_draft_is_committed` 检查块编辑打开后另建并完成主画布草稿：块定义保存按源修订过期拒绝，本地内容及本地撤销/重做保留；人工检查仍待执行。
- `test_block_editor_pastes_text_style_locally_and_saves_atomically` 检查块编辑粘贴带冲突样式的文字、本地撤销重做、保存失败回滚与重试、共享实例显示及保存重开一次撤销；真实桌面操作和参考软件外观仍待人工检查。
- `test_cross_document_mixed_clipboard_pastes_into_block_editor` 与块编辑器的纯几何、混合粘贴、平面及不支持载荷定向测试，检查几何文字和样式的局部事务、拒绝边界及保存重开；不等于参考软件人工验收。
- [联合时间线测试](../../tests/app/test_drawing_collection_timeline.py)的 `test_group_block_combined_timeline_cancel_or_reopen` 覆盖已保存线和草稿线编组、复制、转块的暂存撤销/重做及取消；提交草稿后继续插入实例、编辑共享定义、分解，保存重开再逐步撤销/重做。按产品规则，进入块编辑前先完成草稿。此测试使用应用接口，不等于真实桌面操作通过。
- [文档生命周期测试](../../tests/ui/test_drawing_collection_lifecycle.py)覆盖空画布的集合暂存保存、多文档切换后恢复组及块、保存失败后的暂存与写入保护恢复、重试及重开撤销；实际桌面验收仍待记录。
- [窗口联合流程测试](../../tests/ui/test_drawing_collection_workflow.py)通过命令栏和块编辑画布执行 GROUP、COPY、BLOCK、INSERT、BEDIT、BSAVE 和 EXPLODE，分别检查取消草稿与提交后重开逐步撤销/重做，并验证两个实例的共享定义更新。该测试在离屏 Qt 环境运行，不代替真实桌面或 AutoCAD 人工验收。
- [组会话测试](../../tests/ui/test_drawing_collection_session.py)的 `test_groupedit_removing_last_member_deletes_group_but_preserves_object` 覆盖最后成员移除、重叠组目标、失败回滚及重开撤销；[块编辑测试](../../tests/ui/test_drawing_block_editor.py)的 `test_bedit_rejects_empty_draft_with_staged_saved_object_edit` 覆盖空画布仍存在混合暂存时的进入拦截与撤销。
- [组会话测试](../../tests/ui/test_drawing_collection_session.py)的 `test_group_rejects_stale_picked_geometry_instead_of_using_same_id_from_other_sketch` 和 `test_group_rejects_stale_picked_dimension_with_same_id_in_other_sketch` 检查来源失效时不回退到另一草图的同 ID 对象；前者还覆盖 BLOCK、COPY 和删除入口。
- [混合对象窗口测试](../../tests/ui/test_drawing_block_commands.py)的 `test_full_mixed_group_cross_document_clipboard_from_block_seed` 覆盖以块实例为种子的完整混合组跨文档复制；[草稿会话测试](../../tests/ui/test_drawing_collection_session.py)的 `test_draft_constraint_and_group_delete_share_collection_transaction` 覆盖约束和组成员混合删除的失败回滚与持久撤销。
- [草稿会话测试](../../tests/ui/test_drawing_collection_session.py)的 `test_group_clipboard_pastes_ellipse_from_its_center` 覆盖完整椭圆和椭圆弧组的粘贴预览、放置、撤销重做及保存重开撤销；[旧剪贴板测试](../../tests/ui/test_drawing_clipboard.py)的 `test_legacy_clipboard_pastes_ellipse_from_center` 覆盖旧几何及几何加图片载荷。
- [块画布测试](../../tests/ui/test_drawing_block_tools.py)的 `test_fit_view_includes_ellipse_and_block` 覆盖普通草稿或已保存椭圆与远处块共同适应窗口；`test_fit_view_uses_actual_layer_for_same_id_background_geometry` 覆盖跨草图同 ID 对象的可见、隐藏及冻结图层判断。
- 同一测试文件的 `test_fit_view_includes_rotated_picture_and_block` 覆盖图片旋转、镜像和隐藏层；`test_fit_view_resolves_each_dimension_in_its_source_sketch` 覆盖跨草图同 ID 尺寸的几何来源。[图片交互测试](../../tests/ui/test_drawing_raster_paste.py)的 `test_picture_window_and_crossing_selection` 验证共用图片角点后的窗口和交叉框选。
- 同一测试文件的 `test_rotated_picture_block_group_clipboard_preview_matches_committed_display` 覆盖旋转工作平面下图片与块的组复制、移动预览及提交显示；`test_rotated_legacy_mixed_paste_reopens_with_geometry_and_image_aligned` 覆盖旧几何加图片载荷的真实提交、重开及撤销重做。普通文字、参考尺寸、公差框和基准的旋转平面显示与操作已有定向测试，具体范围及仍需核查的边界见进度记录；复杂自动路由和人工外观尚未由这些测试证明。
- 同一测试文件的 `test_rotated_legacy_mixed_annotation_paste_reopens_atomically` 和 `test_rotated_legacy_mixed_geometry_picture_and_frame_reopens_atomically` 覆盖旧混合标注、几何和图片载荷在旋转平面的真实提交与重开后一次撤销；`test_mixed_annotation_transform_rejects_work_plane_change` 检查指定基点后切换平面时取消移动或复制。
- `test_rotated_partial_group_clipboard_preserves_dimensions` 覆盖旋转视图中关闭组选择后的尺寸、文字和公差混合复制、同 ID 来源区分、失败时剪贴板不变及重开撤销；`test_rotated_partial_group_mixed_clipboard_pastes_across_documents` 使用两个真实窗口检查跨文档预览、相对位置和一次撤销/重做，不代表参考软件人工验收。
- `test_group_clipboard_external_datum_same_and_cross_document` 检查组外基准的同文档保留、跨文档解除提示及重开撤销；[剪贴板测试](../../tests/app/test_drawing_collection_clipboard.py)另覆盖外部几何、标注目标、来源变化和载荷校验。人工外观与提示仍待验收。
- `test_group_clipboard_changed_external_target_fails_and_can_retry` 在真实窗口中检查复制后目标变化导致粘贴拒绝、文档和暂存状态不变、取消及重新复制后成功；`test_external_clipboard_tracks_live_document_across_workspace_switches` 检查不同文档隔离和切回原文档的关联保留。
- `test_rotated_group_move_keeps_attached_datum_and_block_together` 从块实例点选混合组，检查旋转视图中的预览与暂存结果、基准附着目标跟随及撤销；`test_mechanical_auto_normal_on_coplanar_view` 检查同向和反向共面视图下公差框及基准的几何附着与法向引线。
- `test_rotated_legacy_mixed_geometry_picture_and_frame_reopens_atomically` 另覆盖从旋转视图复制带尺寸和水平约束的来源草图；`test_legacy_mixed_copy_rejects_ambiguous_constraint_identity` 覆盖跨草图同 ID 约束选择的歧义拒绝。
- `test_legacy_constrained_paste_keeps_source_plane_in_collection_session` 覆盖旧版纯几何剪贴板的约束、尺寸和样式在旋转共面视图中的粘贴、取消和持久撤销；非共面视图的拒绝另有定向测试。
- 极端比例文字：`test_canvas_renders_visible_portion_of_extremely_large_block_text` 覆盖 `1e10` 和 `1e200` 的直线、曲线字形；`test_extremely_large_block_text_preserves_glyph_hole` 检查孔洞，`test_extremely_large_rotated_block_text_is_visible` 覆盖旋转实例。其他字形及真实桌面性能仍需继续核查。
- 同一块画布测试文件的 `test_group_affine_copy_is_one_staged_operation_with_frozen_preview` 覆盖几何、文字、图片与块实例组的旋转/缩放副本，验证点选和数值输入、预览身份及重开撤销重做；`test_group_affine_copy_from_command_bar`、`test_affine_copy_of_one_member_does_not_join_unselectable_group` 分别覆盖命令栏与关闭组选择后的部分复制。过期预览、候选失败重试以及块实例层锁定、隐藏、冻结的整次拒绝由同文件的对应定向测试覆盖。
- [组变换测试](../../tests/app/test_drawing_collection_move.py)的 `test_group_affine_rebinds_inferred_rectangle_references` 覆盖矩形自动重合、相切在旋转、缩放和镜像后的引用及重开撤销；`test_rectangle_group_affine_rejects_unproven_rebinding_atomically` 检查旧版本和错误依据的拒绝。真实画布路径由 [组会话测试](../../tests/ui/test_drawing_collection_session.py)的 `test_group_rectangle_rotation_rebinds_inferred_vertex_from_canvas` 覆盖，人工结果仍须按清单记录。

证据索引不替代版本化验收记录。当前环境未发现 AutoCAD 或 Wine 命令；不可据此推定其他计算机的安装情况。`DISPLAY` 存在也不等于已完成真实桌面人工操作。未执行或失败的项目应保持原状态，不用自动测试代填人工结果。
