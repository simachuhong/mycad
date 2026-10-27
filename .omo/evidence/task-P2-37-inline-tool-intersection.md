# P2-37 — 内联工具体交集（阶段性证据）

日期：2026-10-25。状态：**partial；P2-37 与 P2 G 均未完成**。本记录只覆盖当前模型与一个内联基本体的交集，不代表任意实体间 Boolean 或 Solid Edge 桌面验收完成。

## 交付

- 释放 `modify.boolean_intersect@1`，CLI alias 为 `intersect`，参数复用既有内联 box/cylinder `Tool` schema。操作将当前聚合模型与指定工具体求交，工具体消耗，只保留非空公共实体。
- 几何运算位于 `mycad.geom`。空模型、空交集和无实体结果以 `GeometryBuildError` 失败；失败不改变 kernel 当前几何，也不增加 Bus 历史。
- 命令接入注册表、计划确认表、CLI 命令列表与解析、命令速查、左侧命令库、主菜单、参数栏和定制矢量图标。UI 在 XY 工作平面放置工具体，自动显示候选预览，只有显式确认才经 Command Bus 提交。
- `.mc.json` 沿用命令历史语义；未增加运行时 `BodyId`/`TopologyId` 存档引用。交集参数支持 Bus 保存重开、撤销、重做。
- 补上 `BuildKernel.apply` 的入口类型检查，保证非 mapping 参数按既有 `ValidationError` 契约返回，而不是在 `.get()` 处抛 `AttributeError`。更新历史隔离测试使用当前版本化 handler key，避免把 @1 handler 错配到 `feature.revolve@3`。

## Solid Edge 自检

Siemens Solid Edge 的 `BooleanFeatures.Add` API 把 intersect 列为独立 Boolean 操作，并规定交集的工具数组应包含实体体。MyCAD 目前通过显式放置的内联盒/圆柱提供该工具，符合布尔操作与预览确认意图；因为项目尚未定义稳定的实体间引用/lineage 生命周期，此首片不宣称支持任意现有实体选择。

参考：[Siemens Solid Edge BooleanFeatures.Add API](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/SolidEdgePart~BooleanFeatures~Add.html)。

## 验证

- P2 G 定向集：**949 passed**（127.13 秒）。覆盖 builtin/schema、CLI、core、geom、app、计划确认、拾取、菜单、主题、草图编辑、scope、layering 与 ADR 文档测试。
- 交集新增测试覆盖盒/盒与盒/圆柱解析体积、空模型、空交集、CLI 别名+undo、grammar 往返、Bus 保存重开/undo/redo/失败不写历史、UI 预览后显式确认。
- Ruff check 通过；Ruff format check **25 files already formatted**；basedpyright **0 errors / 0 warnings / 0 notes**；`git diff --check` 通过。

## 仍待完成

- 任意已建实体之间的 Boolean 并/交、目标选择、工具体保留、多个工具/结果和来源 lineage 尚未支持；交集目前只接受一个内联 box/cylinder，失败不保留工具体。
- P2-37 还缺实体移动/旋转/复制/镜像、通用线性/环形阵列和多实体关系；倒角也只有等距模式。
- P2-32～36 和 P2-44 的任务级验收仍未关闭；用户明日手工走查与 Solid Edge 桌面比较待做。
