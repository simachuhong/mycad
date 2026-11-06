# 独立二维 AutoCAD 交互验收基线

日期：2026-11-04。范围为独立二维文档，零件内草图和工程图分别见 [ST10 基线](solid-edge-interaction-acceptance.md)。需求依据：[统一 UI 设计](2026-11-04-unified-ui-design.md)及 [U00/U09 清单](2026-11-04-unified-ui-todo.md)。

## 对照配置

对照版本为 **AutoCAD 2023 或 2025 完整版**，根据用户 2026-11-05 的确认，两者均可作为验收依据；每项记录实际使用的版本，版本间差异单独登记。用户提供的[中文界面截图](../../.omo/evidence/ui-redesign/reference-autocad2025-start-user.png)称为“经典模式 UI 布局”；截图显示启动页和功能区，不足以证明实际工作区名称、模型空间布局或命令行位置。另有[英文操作录像取样](../../.omo/evidence/ui-redesign/autocad-video-reference/observations.md)，实际标题显示 AutoCAD 2023、Drafting & Annotation，虽视频标题称 2025，仍按画面版本登记。产品更新号、操作系统、系统缩放、输入法、鼠标、快捷键及是否定制仍待核对；不得将 LT 或垂直工具集冒充上述版本。录像只覆盖部分二维步骤，参考核对和用户验收尚未完成。

用户补充的 [AutoCAD 二维练习录像目录及初步取样](../../.omo/evidence/ui-redesign/autocad-exercises-reference/observations.md)包含 79 段视频；目前辨认出部分画面为 2018 和 2020，作为布局与绘图场景参考，仍与 2023/2025 验收依据分开记录。尚未逐段观看或确认其余录像版本。

已核对的文档级事实：[Autodesk 2025 状态栏速查](https://help.autodesk.com/cloudhelp/2025/ENG/AutoCAD-Core/files/GUID-E3B34B0A-EA98-45E9-937A-BF5FEF4152DB.htm)列出栅格、捕捉、正交、极轴追踪、动态输入及对象捕捉；[动态输入](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-Core/files/GUID-C5381B8D-FAE1-437D-BC08-6D279073A61C.htm)描述光标附近命令输入及 F12；[工具栏](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-Core/files/GUID-42E68723-BEBB-4572-B3B1-3C43E252FCF1.htm)说明快捷访问工具栏及工作区保存。它们不证明其他未列细节或 MyCAD 符合。

## 分项验收与证据

所有行初始状态：**参考待核对；工程待实现或待复验；用户未验收**。测试名仅指出候选覆盖，未代表本包已运行或涵盖整行。

| 编号 | 范围与人工操作证据 | 自动验证入口 | 所属包 |
| --- | --- | --- | --- |
| ACAD-01 | 对照绘图/修改分组；逐工具绘制、取消、重复，截图及录像 | `tests/ui/test_sketch_editor.py` | U09 |
| ACAD-02 | 按钮和键入命令切换、选项、Esc/Enter/空格/右键；记录焦点与中文输入法 | 新增二维交互命令行测试 | U09 |
| ACAD-03 | 绝对/相对/极坐标与动态输入实测数值，记录吸附开启/关闭 | `tests/ui/test_sketch_editor.py`，新增命令行测试 | U09 |
| ACAD-04 | 状态栏网格、栅格捕捉、正交、对象捕捉、极轴追踪各自操作，记录未实现项 | `tests/ui/test_sketch_editor.py` | U09 |
| ACAD-05 | 图层显示/冻结/锁定，框选/交叉选择、夹点和特性联动；逐状态录像 | `tests/ui/test_sketch_editor.py` | U09 |
| ACAD-06 | 普通与驱动尺寸逐项改值、撤销、重开，核对旧档语义 | `tests/ui/test_sketch_editor.py` 及保存测试 | U09 |
| ACAD-07 | 绘制→修改→图层→标注→保存重开→DXF 输出和报告 | `tests/ui/test_sketch_editor.py`、`tests/ui/test_document_save_session.py` | U09/U13 |
| ACAD-08 | 切换零件和工程图再返回；核对二维布局、草稿、UCS、图层及历史 | `tests/ui/test_workspace_tabs.py`、`tests/ui/test_document_session.py` | U02/U09/U13 |

每次记录产品及更新号、工作区、语言、分辨率/缩放、MyCAD commit 与工作区状态、操作步骤、预期/实际、截图或录像、差异及用户是否接受。不得将自动测试结果直接记为参考核对或用户验收通过。

## 已核对的 2025 官方文档要点

以下是文档参考，不是对指定实机配置或 MyCAD 实现的验收：

| 关联项 | 文档内容 | 仍需实机核对 |
| --- | --- | --- |
| ACAD-02/03 | [指针输入坐标](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-Core/files/GUID-A265C30C-CFD8-405D-BEE2-257B379475E2.htm)说明启用动态输入、笛卡尔和极坐标输入，以及尺寸字段输入后 Tab 锁定。 | 命令行与动态输入的具体优先级、每种命令和输入法操作。 |
| ACAD-04 | [状态栏速查](https://help.autodesk.com/cloudhelp/2025/ENG/AutoCAD-Core/files/GUID-E3B34B0A-EA98-45E9-937A-BF5FEF4152DB.htm)分别列出网格显示、栅格捕捉、正交、极轴、对象捕捉和动态输入。 | 默认显示哪些按钮、各选项和定制工作区状态。 |
| ACAD-05 | [夹点编辑](https://help.autodesk.com/cloudhelp/2025/ENG/AutoCAD-Core/files/GUID-01DE459C-21A7-4E92-A1D6-E2C36CD89F0C.htm)说明夹点可用于编辑，锁定图层上的对象不显示夹点。 | 框选/交叉选择、每种对象夹点行为及与图层设置的交互。 |

对未列细节、不同产品版本和 MyCAD 的行为不作推断；录制时必须附实际更新号和配置。
