# P2-37 — 常规三维修改（首个切片：等距倒角）

日期：2026-10-25。状态：**partial，P2-37 仍在开发**；这不是 P2-37 完成或 Solid Edge 人工验收通过。

## 已交付

- 释放 `modify.chamfer@1`，CLI alias 为 `chamfer`。参数 `edges` 必须是非空稳定/交互边选择器数组，`distance` 必须大于 0 mm；一条命令内所有边使用同一个等距 setback。
- 几何适配层解析并去重选择边，以等距形式构建 chamfer；无实体、无边、非法距离或 OCCT 失败不会生成有效预览/历史命令。
- 共享建模工具栏从视口选择一条或多条边，修改距离时更新临时预览，只有显式确认才经计划卡片和 Command Bus 写入历史。取消/错误预览不写命令；修正尺寸后可恢复操作。
- 将 `chamfer_edge` 加入 `AffectedObject` 与计划确认表，保留旧值和旧命令 schema。
- 修正了两个在该批回归中发现的已发布命令问题：CLI `commands` 对无别名命令现在显示空 `verb` 字段，不再索引空元组；CLI parser 在 `oneOf` 对象数组中递归物化数字索引，恢复圆角与倒角的对象数组往返。

## Solid Edge 对标

采用 Siemens Solid Edge Fundamentals 中 Chamfer Feature Workflow 的基本顺序：选择边、预览、完成；Equal Setback Chamfers 支持同一操作选择多个边并共享 setback 值。其 `AddEqualSetback` API 将 setback 距离定义为沿相交面从公共边量取。实现通过非交叠的长方体边做了解析体积核对，并在 UI 中验证双边选择、同一 setback、失败恢复与确认提交。

参考：[Solid Edge Fundamentals — Chamfer Feature Workflow / Equal Setback Chamfers](https://support.industrysoftware.automation.siemens.com/training/se/en/ST5/pdf/mt01413-s-1050_en.pdf)，[Solid Edge Part API — AddEqualSetback](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgePart~Chamfers~AddEqualSetback.html)。

## 验证

- 相关 CAD、命令 schema、UI、Bus、存档、scope、layering 与 ADR 集合：**278 passed**（78 秒）。
- 新增的双边选取、超限预览拒绝/恢复 UI 回归：**1 passed**；Chamfer Bus 保存重开/undo/redo 与 CLI 往返在应用执行集内通过。
- Ruff check 通过；Ruff format check 通过；basedpyright **0 errors / 0 warnings / 0 notes**；`git diff --check` 通过。

### 后续切片：内联工具体交集

2026-10-25 后续释放 `modify.boolean_intersect@1`：当前聚合模型与放置的 box/cylinder 工具体求交，工具体消耗，空交集拒绝写历史；支持 CLI `intersect`、UI 预览/显式确认、Bus 保存重开和 undo/redo，不存运行时 body ID。对照 Siemens [BooleanFeatures.Add API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgePart~BooleanFeatures~Add.html) 的实体交集工具输入。扩展 P2 G 回归集合 **949 passed**（127.13 秒）；Ruff、format、basedpyright 与 diff 检查通过。实体间引用/保留工具、多实体关系、变换和通用阵列仍未交付。完整契约与限制见[内联工具体交集证据](task-P2-37-inline-tool-intersection.md)。

## 未覆盖 / 下一步

- 仅等距 setback；角度+setback、双 setback、参考面模式尚未支持。
- P2-37 余下的任意实体间并集/交集、实体移动/旋转/复制/镜像、通用线性/环形阵列、工具体保留和多实体关系仍待实现；当前内联工具交集不能替代实体间操作，P2-37 不可标记完成。
- 未进行 Solid Edge 桌面人工流程对比；用户明日人工测试与验收待进行。
