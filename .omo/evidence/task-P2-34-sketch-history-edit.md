# P2-34/P2-36 — 历史草图编辑与下游重建（阶段性证据）

日期：2026-10-25。状态：**partial，仍在开发**；本记录不表示 P2-34/P2-36 完成，也不表示 Solid Edge 人工验收通过。

## 本轮交付

- 结构树将 `sketch.create` 命令放在独立“草图”组；几何特征仍放在“特征”组。选中草图后显示“编辑选中草图…”，选中特征则保留“编辑选中特征…”。
- 草图编辑使用现有历史编辑预览/确认流程，通过 `CommandBus.edit_and_replay` 修订原命令，不旁路 Bus。预览展示规范化参数变化及下游命令数量；确认后追加 amendment、保留原始时间戳并重放后续历史。
- 回归场景创建半径 5 mm 圆草图并拉伸 10 mm，编辑草图半径为 6 mm 后确认；草图与图元 ID 保持不变，原始时间戳保持不变，amendment 记录旧值，下游实体体积更新为 `360π mm³`。
- 参数表单根节点现在可渲染根级 `oneOf`。新版孔命令的旧式面孔参数和草图孔参数都可选取正确分支；不完整旧式参数可用其独有字段推断分支，保持视口面选择器的 `target_face` 填充入口。空白孔表单显示“面孔”和“草图孔”，次级选项显示“几何条件/视口锚定面”“面心/指定点”“贯穿/盲孔”，未选择根分支时给出 `ValidationError`。
- 左侧命令库将已释放的 `sketch.*` 命令显示在中文“草图”组，保持按注册表显示最新命令的行为；旧验收中的“固定为 8 条”断言改为覆盖所有当前注册命令，避免以后新增已释放命令时把正确变化误判为故障。

## 自动验证

下列 P2 G/core/geom/UI 相关测试集合通过 **127 项**（26.68 秒）：

```bash
uv run pytest \
  tests/core/test_sketch.py tests/core/test_sketch_constraints.py tests/core/test_schema_v2.py \
  tests/geom/test_sketch_commands.py tests/geom/test_sketch_constraints.py \
  tests/geom/test_sketch_extrusion.py tests/geom/test_sketch_holes.py \
  tests/geom/test_profile_workplane_prototype.py tests/ui/test_sketch_editor.py \
  tests/ui/test_parameter_forms.py tests/ui/test_history_edit.py \
  tests/ui/test_modeling_interaction.py tests/ui/test_sketch_constraint_dialog.py \
  tests/ui/test_right_tabs.py tests/ui/test_body_tree.py -q
```

改动相关路径的 `ruff check`、`ruff format --check`、`basedpyright`（0 errors / 0 warnings / 0 notes）与 `git diff --check` 均通过。没有运行全项目测试集，也没有运行本地桌面人工流程。

补充的命令库、代表零件、P0 法兰验收与 Bus 回放集合通过 **102 项**：

```bash
uv run pytest tests/ui/test_command_palette.py tests/scenarios \
  tests/test_acceptance_flange.py tests/core/test_bus.py -q
```

这次自检修正了命令库分组回归和过期的数量断言；之前的失败结果是旧断言仍假设只有 P0 的 8 条命令，不是几何/Bus 行为失败。

## Solid Edge 交互基线对照

按 [Solid Edge 鼠标操作研究](../../docs/design/solid-edge-mouse-interaction-study.md) 与代码/测试对照；该记录基于 Siemens 公开教程/文章，未进行 Solid Edge 实机复现：

- **导航和选择反馈**：MyCAD 视口已使用中键旋转、Shift+中键平移、滚轮缩放；悬停预选与点击确认分离，框选区分窗口包含和交叉选择，建模命令中也保持中键导航。相应自动覆盖在 `tests/ui/test_navigation_contract.py`、`tests/ui/test_picking.py`。
- **草图绘制**：未提交草图保持在可见的画布草稿中；点位捕捉会给出类型提示，现可在当前编辑会话临时关闭。鼠标和 U/V 坐标输入共用相同的局部毫米坐标与捕捉路径；直线/折线支持正交输入，鼠标与数值方式均有回归；端点/中点/圆心/直线、线圆、圆圆、弧范围内交点、当前线端点的垂足和切点均有自动用例。多个候选处距离相同则按端点、交点、垂足、切点、圆心、中点、中心优先，避免结果随图元加入顺序变化。
- **特征预览和接受**：拉伸/旋转/孔的预览先显示候选几何，确认后才经 Bus 提交；历史编辑预览呈现参数差异与下游数量，确认后重放下游命令。取消不修改命令历史。
- **仍落后于参考流程**：重叠对象尚无 QuickPick 候选清单；草图画布没有选择后拖动/删除任意既有图元（目前仅能撤销最后新建图元）；已提交草图的编辑使用参数历史对话框，尚无就地操纵柄；当前也未有 Solid Edge 实机对照记录。明日人工走查应优先确认这些差异对实际任务的影响。

Solid Edge 草图教程将图形窗口点击与命令栏数值输入并列，说明 IntelliSketch、Intent Zones、Grid 用于关系推断与精确输入，也列出修剪、延伸、分割、偏移、移动、旋转和镜像等编辑；MyCAD 目前只匹配绘制、坐标输入与基础点位捕捉，编辑链仍明显不完整。[Siemens Sketching 教程](https://support.industrysoftware.automation.siemens.com/training/se/en/ST4/pdf/spse01510-s-1040_en.pdf) 和 [Solid Edge 2D Drafting 产品说明](https://solidedge.siemens.com/wp-content/uploads/2021/09/Siemens-SW-Solid-Edge-2D-Drafting-FS-82952-D6.pdf)。QuickPick 候选列表是 Draft 环境的选择参考，不能直接推广成所有 Part/Sketch 环境的行为。[Siemens QuickPick 文章](https://blogs.sw.siemens.com/solidedge/Select-and-you-are-all-Set/)。

2026-10-25 后续补足 P2-34 交互：用同一屏幕半径内的重合候选确认端点胜过中点；用临时复选框关闭捕捉后，近邻坐标保持原值；新增正交输入，仅约束直线/折线的后续点，捕捉到既有几何时保留捕捉点；从当前线端点计算有限线段垂足与圆/弧切点，并通过状态栏显示捕捉种类。新增回归覆盖折线逐点锁轴、鼠标落点、垂足和切点。`tests/ui/test_sketch_editor.py` **21 passed**；合并 P2 G/core/geom/UI/范围和 ADR 关联集合 **200 passed**；触碰 Python 路径的 Ruff、格式、basedpyright 和 `git diff --check` 通过。

## 明日人工走查建议

1. 在 Solid Edge 与 MyCAD 中各完成：新建草图 → 画圆 → 输入尺寸 → 完成草图 → 拉伸；记录开始命令、预览、接受与取消的鼠标/键盘动作。
2. 在 MyCAD 结构树选中草图并编辑圆半径 5→6 mm；确认对话框明确列出参数变化与一条下游特征；确认后检查预览/实体尺寸，取消则确认历史和体积不变。
3. 打开新版孔参数表单，确认“面孔/草图孔”意图可辨；用视口拾取补全目标面，分别预览、取消、确认，检查旧 `feature.hole@1` 历史仍可编辑并回放。
4. 对照 Solid Edge 鼠标研究记录验证草图的端点、中点、圆心、交点、切点、垂足捕捉与会话内捕捉/正交开关，顺/逆时针圆弧、Esc 取消及取消后模型/历史保持；记录本机分辨率和显示缩放。

## 尚未覆盖

这只交付了通过参数历史编辑来修改草图并重建下游特征的首个垂直切片，以及捕捉优先级和临时关闭的独立交互改进。自动推断关系、重叠 QuickPick、直接拖动既有图元、删改引用的保留/迁移/失效规则、修剪/延伸/分割/偏移、完整约束编辑和 Solid Edge 实机对照仍未完成；P2-32～37 与 P2-44 仍保持未完成状态。
