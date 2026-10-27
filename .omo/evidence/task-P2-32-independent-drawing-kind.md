# P2-32 — 独立二维文档类型与保存重开（阶段性证据）

日期：2026-10-25。状态：**partial，P2-32 与 P2 G 均未完成**。本切片补齐独立二维文档身份和流程，不代表 Solid Edge 人工验收通过。

## 交付

- 新增 `.mc.json` v3，强制顶层 `document_type` 为 `part` 或 `drawing2d`；v1/v2 结构保持不变，旧版档案仍解释为 `part`。新二维图明确保存为 v3，不根据 `sketch.create` 或元数据猜文档类型。
- `Document.document_type` 在实例生命周期内只读；新建二维图必须从 v3 起步。含草图的零件仍按 v2 保存并保持 `part` 身份。
- 二维图 Bus 只接受明确释放的 `sketch.create@1` 与 `sketch.constraint.add@1`。严格档案校验在重放前拒绝非草图命令和 3D 命名组，Bus 再作运行时保护。
- 文件菜单增加“新建二维图”。切换到二维图后，命令库仅列草图命令，三维特征菜单禁用；保存/打开沿用现有 `.mc.json` 路径，导出入口仅提供 DXF。
- 新增 ADR-011，记录类型、迁移、命令白名单和产品边界。README 与 Solid Edge 操作验收基线同步更新。

## 兼容性

- 旧 v1/v2 档案不写 `document_type`，打开后维持 `part`。v2 provenance、审计字段和命令参数均由既有迁移继续保留。
- 新二维档案写 v3 并记录类型；零件的既有 v1/v2 保存语义不变。
- 新文档类型没有建立新的几何或存档旁路：草图仍是 Bus 命令历史，撤销/重做/重放沿用原机制。

## 验证

测试先红：新 v3 校验器与 `DocumentType` API 尚不存在时，两个新增测试模块在收集阶段失败。补齐实现后，以下定向集完整通过：

```text
uv run pytest tests/core/test_schema_v3.py tests/core/test_document_kind.py tests/core/test_schema_v2.py tests/core/test_persistence.py tests/core/test_bus.py tests/core/test_document.py tests/app/test_composition.py tests/ui/test_document_lifecycle.py tests/ui/test_command_palette.py tests/ui/test_menus_toolbar.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
229 passed in 80.26s

uv run ruff check <changed Python paths>
All checks passed

uv run ruff format --check <changed Python paths>
16 files already formatted

uv run basedpyright <changed Python paths>
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

回归覆盖：严格 v3 结构、两种合法类型、未知字段/版本/类型拒绝、二维图 3D 命令与 3D 命名组拒绝、拒绝前不触发几何、独立二维图 v3 保存/重开、旧 v2 保持零件身份、含 `sketch.create` 的零件仍保持零件身份、UI 新建/保存/重开、菜单和命令库过滤、分层/命令范围/ADR 文件约束。

另一个范围更宽的测试命令同时覆盖整个 core/geom/CLI/格式目录和多组 UI；运行 5 分 58 秒未产出最终摘要，已停止且**不计入通过结果**。这不是全仓测试结论。

## Solid Edge 自检与人工验收

Siemens 官方资料将独立 2D Model sheet 与草图/工程图工作流列为不同用途；其草图还支持更多 2D 编辑、关系提示和驱动尺寸。当前交付只补文档类型、草图命令边界和存档闭环，MyCAD 的偏移/移动/复制/旋转/镜像、自动推断、拖柄、图层和尺寸标注仍未交付。参考 [Solid Edge 2D drawing elements](https://support.industrysoftware.automation.siemens.com/training/se/en/ST4/pdf/mt01419-s-1040_en.pdf)、[Solid Edge Sketching](https://support.industrysoftware.automation.siemens.com/training/se/en/ST5/pdf/mt01413-s-1050_en.pdf) 和 [Working with Dimensions](https://support.industrysoftware.automation.siemens.com/trainings/se/106/api/WorkingWithDimensions.html)。

明日人工验收：

1. 从“文件 → 新建二维图”开始，绘制、保存、退出并重开；检查类型为 `drawing2d`、图元身份/工作平面/单位不变、模型中没有 3D 实体。
2. 在二维图中尝试长方体、拉伸、布尔等三维命令；应从菜单不可用，并由 Bus 拒绝程序化提交。
3. 用 DXF 导出并在下游 CAD 检查线、圆、弧、矩形、构造几何及交换报告；确认只交换明示子集。
4. 新建零件、创建草图后保存重开，确认文档类型仍是 `part`，旧 v1/v2 样本照常打开。
5. 对照 Solid Edge 实机记录命令步骤、预选/纠错、精确输入、撤销和保存重开体验。自动化结果不代替这一步。

剩余工作包括关联模型面的草图、圆弧/圆交点捕捉与编辑、混合曲线闭环条件，以及 P2-33～P2-37 仍未实现的交互和建模范围；计划中的 P2-32 勾选仍保持未完成。

## 后续实现与收敛自检

上面的缺口清单记录的是独立二维类型首片完成时的状态。后续 P2-34/P2-35 实现已加入选面附着草图、圆/圆弧交点捕捉与草稿修剪/延伸、图层和标注/DXF 子集；对应测试现由全仓回归覆盖，最近一次 `uv run pytest -x -q -o faulthandler_timeout=90` 为 **1518 passed in 308.19s**。这不表示草图支持任意面附着编辑、任意 DXF 实体/外部标注或 Solid Edge 等价操作；任务勾选仍需在用户桌面验收后更新。
