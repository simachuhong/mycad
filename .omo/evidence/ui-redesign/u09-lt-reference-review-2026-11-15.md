# U09 再评审与 AutoCAD LT 官方文档对照

日期：2026-11-15。用户要求复查 U09（UI09）未收口任务，并参考 AutoCAD 2023 或 2025 的 LT 版官方文档提出补充。

## 结论和审查范围

既有用户验收仍有效。本轮在核对范围内未发现新的 P0/P1 阻断缺陷，但发现一项明确的已有功能 CLI 遗漏：“分割（附近交点）”不能从命令行启动，且原覆盖表误将 BREAKATPOINT 写作其覆盖方式。另有收口记录滞后，以及两项最新界面修改缺少独立设备反馈。

本轮检查当前工作区源码、U09 原清单、收口/设备/进度记录和命令覆盖表，并独立复核入口语义；实际运行了一个离屏命令入口探针。未改产品代码，未运行全量或重复历史测试。既有测试通过数仅为原记录证据；不代表本轮复跑或当前全量结果。审查不是对全部几何组合的穷尽证明。

参考以 **AutoCAD LT 2025 Windows 官方帮助**为主，DIMLINEAR 使用可访问的 **LT 2023 Windows**页面。文档核对不等于运行 AutoCAD 实机对照，也不补造用户本人参考软件版本。原完整版/录像基线保留，LT 作为本次补充参考。

## 尚未收口或需要整理的事项

| 项目 | 判断 | 处理建议与依据 |
| --- | --- | --- |
| P2：分割的命令入口 | 明确的工程遗漏 | 工具栏“分割”按附近交点分割，`core/sketch_edit.py:1675`；`drawing2d_command_bar.py:219` 映射没有此工具。BREAKATPOINT 是指定目标和打断点的另一操作，`sketch_editor.py:11597`。应补同语义命令及拾取/坐标、取消、撤销、重复流程；命名不能冒充尚未实现的 AutoCAD BREAK。 |
| P2：收口记录互相矛盾 | 本轮已订正文档 | `u09-current-status.md` 的连续 CLI 待复验及两个验收文件“用户是否接受：待填写”与后续反馈矛盾。现已更新，保留未覆盖范围；命令覆盖表也已拆开“分割”和 BREAKATPOINT。 |
| 原总任务表及命令实施计划仍未勾选 | 状态归档还不完整 | `docs/design/2026-11-04-unified-ui-todo.md:127`、`docs/superpowers/plans/2026-11-15-u09-command-coverage.md` 仍使用广泛未完成项。应按已接受范围、真实遗漏和后续增强分项整理，不能全部勾选成完整 AutoCAD 等效，也不能据空勾选要求重做已通过验收。 |
| 约束标记显隐 | 工程已实现，设备证据未补 | 设置、已有/新建图纸同步、取消和独立进程重启已有定向证据；`tests/ui/test_drawing_constraint_visibility.py`。隐藏非尺寸标记，约束数据保留。尚无明确用户设备反馈。 |
| 倒角按钮对齐 | 工程已修复，设备证据未补 | `sketch_editor.py:15596` 尺寸策略已与圆角一致；`tests/ui/test_toolbar_workspaces.py:44` 定向回归，前轮记录为 1 passed。本轮未复跑。用户的“好的”不扩写为逐项设备复验通过。 |

POINT、DIMRADIUS、DIMLINEAR、POLYGON E 的独立设备反馈，以及复杂关联混选的更多组合，仍是已披露的证据边界，不据此认定功能失败，也不要求重跑已通过项目。参考详见 [既有收口评审](u09-closeout-review-2026-11-15.md)。

## LT 对照后建议补充的任务

以下为建议优先级，不是用户已批准的新开发范围。先完成已有工具入口，再扩展新的实体和数据模型。

| 顺序 | 建议 | 当前实现与官方依据 |
| --- | --- | --- |
| 1 | 补齐已有面板/视图/设置的 CLI 入口 | 实际探针确认 LAYER、PROPERTIES、ZOOM、PAN、OPTIONS 均未知；现有鼠标或界面能力不能代替命令入口。优先复用当前功能，明确支持的选项。[LT 2025 LAYER](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-LT/files/GUID-9123091A-2DCB-4DE8-983C-F7CA38FA67BE.htm)区分面板入口 LAYER 与交互选项 -LAYER，二者不应混称。 |
| 2 | 命令可发现性：补全、Tab 候选、可查询支持列表和选项提示 | 当前连续文本区、上下历史与直接键入已有；`_CommandInput` 使用 `setTabChangesFocus(True)`，没有命令补全机制，未知命令只提示“请输入受支持的命令或坐标”。建议优先支持列表和上下文选项，再做自定义别名。[LT 2025 命令窗口说明](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-LT/files/GUID-BB0C3E79-66AF-4557-9140-D31B4CF3C9CF.htm)说明补全、候选、Tab、别名和透明命令；透明命令可另列后续。 |
| 3 | 标注的生产制图能力 | 当前命令路由支持 H/V，任意空白点、Rotated、Text/Mtext、文字角度等尚不具备对应完整流程。现有精度和比例设置不是命名样式管理。建议普通标注先补必要选项，再引入 DIMSTYLE，明确文字覆盖与驱动值的差别。[LT 2023 DIMLINEAR](https://help.autodesk.com/cloudhelp/2023/ENU/AutoCAD-LT/files/GUID-E908848F-4621-43D2-B377-FD3FBC2B8848.htm)、[LT 2025 DIMSTYLE](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-LT/files/GUID-39D6E54F-E12F-46A4-9DD1-68D9357289E4.htm)。 |
| 4 | 距离、面积、半径、角度查询 | DIST、AREA 当前未知；增加只读查询可避免为了检查几何而创建尺寸。建议先做 DIST/AREA，再考虑 MEASUREGEOM 快速测量。[LT 2025 MEASUREGEOM](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-LT/files/GUID-5D5B0EE1-DD90-47AE-8A55-642FBFF5E4E4.htm)说明命令行/动态提示输出和测量类型。 |
| 5 | 特性编辑和按属性选择 | 当前特性表主体禁止直接编辑，另有图层下拉和尺寸编辑入口，见 `sketch_editor.py:15938`。建议逐类补可编辑几何字段及批量共有属性，再增加按类型/图层筛选；必须沿用 Bus 与约束保护。[LT 2025 Quick Select](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-LT/files/GUID-84E1116E-DEAE-4A0B-9364-F61DACF5C300.htm)支持当前选集/整图、对象类型、属性和包含/排除筛选。 |
| 6 | 新绘图/注释实体作为下一阶段 | 可评估无限构造线 XLINE/RAY、ELLIPSE、HATCH、TEXT/MTEXT、块等，不能仅补别名；独立二维命令路由尚无这些入口，工程图已有的填充/注释不等于二维实体可编辑能力。MyCAD“构造几何”仅是有限图元标记，`core/sketch.py:397` 的 LineEntity 明确是有限线段，不能算 XLINE。[LT 2025 官方速查表](https://damassets.autodesk.com/content/dam/autodesk/www/pdfs/autocad-lt-2025-shortcut-guide-en.pdf)列出相关绘图和注释命令。 |

已有 F12 动态输入及其定向测试，不列为未实现。ARRAYRECT 的单行/单列与角度可表达线性排列，不因缺少独立线性阵列命令就认定能力缺失。PDMODE/PDSIZE、关联环形阵列可继续保留为已知增强项。

LT 的参数化能力需单独理解：[LT 2025 官方限制说明](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-LT/files/GUID-A950070D-4AEB-4F0E-B1D9-0AD53E10048C.htm)明确可以显示/隐藏约束、操作受约束几何及修改参数管理器数值，但不能创建或编辑几何/尺寸约束。因此 MyCAD 的约束创建和驱动尺寸是保留的自身能力，不能依据 LT 限制删除。系统设置全局显隐已满足本次明确要求；按对象或类型显隐属于可选增强。

## 已接受的延期与边界

- STRETCH、BREAK、JOIN、EXPLODE、LENGTHEN、路径阵列按用户此前决定后置，不自动重开为本轮阻塞。
- 环形阵列独立副本、部分关联和 DXF 语义损失、图片不导出等仍以既有评审及交换报告为准。
- Windows/DPI、复杂几何和跨工作区的全面覆盖留在对应 U13/发布阶段范围；当前未重新执行全量测试，不用历史固定摘要声称当前版本全量通过。

## 本轮最小运行验证

执行 `QT_QPA_PLATFORM=offscreen uv run python` 临时脚本，创建真实 `SketchEditorDialog`，在空闲选择状态调用命令栏 `submit()`：

- SPLIT、“分割”、LAYER、PROPERTIES、ZOOM、PAN、OPTIONS、DIMSTYLE、DIST、AREA：均返回“未知命令；请输入受支持的命令或坐标”。SPLIT 只是探测候选，不宣称它是 AutoCAD 标准命令。
- BREAKATPOINT：激活“单点打断”，提示选择直线、圆弧或开放多段线。
- `_TOOLS.values()` 不包含“分割”；结合附近交点分割和指定点打断的两条实现路径，确认入口遗漏。

探针仅验证命令路由，不等于修改几何正确性测试；没有打开或改写用户图纸。文档引用与本轮变更另做定向检查。
