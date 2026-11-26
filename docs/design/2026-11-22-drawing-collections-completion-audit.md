# 二维 GROUP / BLOCK 交付核对

状态：**开发与核对进行中；参考软件和真实桌面人工验收待执行**。本表将交接计划的要求映射到当前实现和具名证据，方便继续查缺；列出的自动测试有通过记录不代表同一范围的人工验收通过。具体执行命令和结果以[进度记录](../../.omo/start-work/drawing-groups-blocks-progress.md)为准，本次建立核对表未重复执行已通过测试。

| 要求 | 当前可检查的证据 | 尚未证明或需要继续核对 |
|---|---|---|
| G0 稳定引用、不可变表、直接所属组选择、成员替换与完整组复制 | [组模型](../../src/mycad/core/drawing_groups.py)、[引用和映射](../../src/mycad/core/drawing_object_refs.py)、[领域测试](../../tests/core/test_drawing_groups.py) | 各普通编辑命令的身份映射须以对应路径验证，不能由领域测试推断全部覆盖。 |
| G1 独立二维状态、v8 命令、文档门控、二维 batch、失败回滚和重开撤销 | [命令注册](../../src/mycad/builtin_commands/drawing_group_specs.py)、[块命令注册](../../src/mycad/builtin_commands/drawing_block_specs.py)、[事务测试](../../tests/app/test_drawing_object_batches.py)、[组命令测试](../../tests/app/test_drawing_collection_commands.py) | 旧注册表模拟缺少新命令可报告错误；未实测具体旧版发行程序。人工操作与兼容结果待记录。 |
| G1 优化重建处理复合命令和分解 | [内核](../../src/mycad/geom/kernel.py)的 `_regenerate_with_sketches`；[块命令测试](../../tests/app/test_drawing_block_commands.py)的 `test_grouped_explode_with_text_survives_optimized_rebuild_and_reopen` | 不能把一次组合测试推断为所有可能的命令历史组合均已覆盖。 |
| G2 已提交对象和草稿的共同时间线、取消、失败恢复、逐步撤销及重开 | [会话](../../src/mycad/ui/drawing_collection_session.py)、[联合时间线测试](../../tests/app/test_drawing_collection_timeline.py)、[生命周期测试](../../tests/ui/test_drawing_collection_lifecycle.py) | 真实桌面和异常情形按[人工清单](2026-11-21-drawing-collections-manual-check.md)继续验收；未接入的文档级写入须保持事前拒绝。 |
| G3 组创建、解组、成员与属性编辑、选择开关和重叠组 | [主窗口](../../src/mycad/ui/main_window.py)、[组管理对话框](../../src/mycad/ui/drawing_collections.py)、[界面测试](../../tests/ui/test_drawing_collection_session.py) | 重叠组目标选择、两方向框选和菜单入口仍需真实桌面人工记录。 |
| G3 多类型整体操作、锁定/隐藏/冻结拒绝、附着标注仅跟随一次 | [事务](../../src/mycad/core/drawing_transactions.py)、[联合界面测试](../../tests/ui/test_drawing_collection_workflow.py)的 `test_numeric_group_move_rejects_locked_block_member` 和 `test_numeric_group_move_translates_attached_datum_and_block_once` | 公差和基准的人工结果未取得；整体操作只允许成员已有的能力。 |
| B0 局部定义、实例正等比变换、样式、0 层继承和确定性展开 | [块模型](../../src/mycad/core/drawing_blocks.py)、[领域测试](../../tests/core/test_drawing_blocks.py) | 块文字、曲线的参考软件外观和真实桌面性能待人工检查。 |
| B1 BLOCK / INSERT、依赖拒绝、实例拾取和坐标捕捉 | [块事务](../../src/mycad/core/drawing_block_transactions.py)、[块命令界面测试](../../tests/ui/test_drawing_block_commands.py)、[画布测试](../../tests/ui/test_drawing_block_tools.py) | 跨块持久关联禁止已有定向验证；实际桌面捕捉及转换提示待人工检查。 |
| B2 BEDIT / BSAVE / BCLOSE、隔离撤销、版本与图层检查 | [块编辑器](../../src/mycad/ui/drawing_block_editor.py)、[块编辑器测试](../../tests/ui/test_drawing_block_editor.py)，含 `test_block_editor_retains_local_edits_after_instance_layer_changes` | 真实桌面保存/放弃/取消及共享实例外观待人工记录。 |
| B2 EXPLODE 的新身份、一对多组映射和定义保留 | [块事务](../../src/mycad/core/drawing_block_transactions.py)、[块命令测试](../../tests/app/test_drawing_block_commands.py)、[块命令界面测试](../../tests/ui/test_drawing_block_commands.py) | 旋转缩放与文字在参考软件中的外观仍需人工对照。 |
| B2 同文档与跨文档剪贴板、定义和样式冲突 | [剪贴板实现](../../src/mycad/core/drawing_collection_clipboard.py)、[剪贴板测试](../../tests/app/test_drawing_collection_clipboard.py)、[界面联合测试](../../tests/ui/test_drawing_collection_workflow.py) | 当前载荷兼容性及跨文档视觉结果仍需真实桌面验收；不可依据测试宣称跨软件剪贴板兼容。 |
| X0 原生 GROUP/BLOCK/INSERT、完整 handle 映射及专用 INSERT 优先 | [DXF 实现](../../src/mycad/formats/providers/dxf_provider.py)、[映射](../../src/mycad/formats/dxf_collections.py)、[格式测试](../../tests/formats/test_dxf_collections.py) | AutoCAD 2023 和 2025 的原生内容修改及往返结果均未取得。 |
| X0 不支持块整体拒绝、图片与组损失报告、重复导入和实际字节预览 | [DXF 导入](../../src/mycad/formats/dxf_collection_import.py)、[导入事务测试](../../tests/app/test_dxf_collection_import.py)、[导入窗口测试](../../tests/ui/test_dxf_collection_import.py) | 参考软件对损失报告所列内容的实际处理待人工检查；预览及导入子集不等于完整 DXF 支持。 |
| 联合链及取消分支 | [真实命令界面测试](../../tests/ui/test_drawing_collection_workflow.py)的 `test_group_copy_block_edit_explode_from_user_commands`；[应用层时间线测试](../../tests/app/test_drawing_collection_timeline.py)的 `test_group_block_combined_timeline_cancel_or_reopen` | 自动路径按规定在 BEDIT 前完成草稿；真实桌面和参考软件结果待记录。 |
| 交接材料和人工结果 | [操作说明、支持矩阵、样图及结果表](2026-11-21-drawing-collections-manual-check.md)、[具名证据索引](2026-11-21-drawing-collections-evidence-index.md) | AutoCAD 2023、2025、真实桌面以及公差人工结果为待执行；用户已决定后续补录。 |

自动证据的范围应按测试本身和进度记录判断。发现用户路径缺口、状态不一致或旧证据已不适用时，先定位并修复，再更新本表；不得因本表存在而认定全部目标已完成。
