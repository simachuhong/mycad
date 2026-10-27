# P2 G 工具栏与默认布局整改（2026-10-25）

状态：三项用户要求已实现，工程验证记录见下；用户人工验收待重启后执行。当前用户 GUI PID 347668 未被本轮编辑关闭或重启。

## 实现

- 命令行和计划所在底栏每次启动均收起，即使上一会话退出时展开；“视图”菜单和主动查看待确认计划仍可打开。
- 绘图、修改、尺寸标注为三个原生 `QToolBar`，由嵌入式 `QMainWindow` 承载，可各自悬浮、四边停靠、同排/分排组合。默认绘图和修改同排，尺寸第二排。保留图标与文本；修剪、延伸、分割归入修改工具栏。
- 二维“工具栏”菜单可单独控制显隐、恢复二维默认布局；主窗口锁定工具栏同时作用于两种工作区。
- 三维建模的长方体、圆柱体、拉伸、旋转、孔、孔阵列、圆角、布尔及实体变换/阵列收进独立“三维建模”工具栏；主工具栏保留文件、视图、撤销等通用入口。仍复用菜单 QAction 和既有确认/执行逻辑。
- 工具栏位置、显隐/悬浮状态保存至 QSettings，跨二维/三维切换、草图提交和窗口重建保持。隐藏二维工作区时同步隐藏其浮动工具栏，返回时恢复；二维期间隐藏三维工具栏。
- 全局布局重置能清除旧二维布局记录。截图检查发现旧的无条件主工具栏重新插入操作会把主栏挤到建模栏同排，已改为仅停靠区域不匹配时重排，并添加默认分行断言。

## 验证证据

证据目录：[phase2-g-toolbar-workspaces](phase2-g-toolbar-workspaces/)。

- 初始针对三项需求的回归：3 failed（缺少工具栏属性、上次展开底栏在启动时恢复），实现后 3 passed。
- 关联回归：`QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_toolbar_workspaces.py tests/ui/test_menus_toolbar.py tests/ui/test_drafting_workbench.py tests/ui/test_drafting_acceptance_round2.py -q` → **73 passed**。
- 新增提交/重建/锁定覆盖后：`QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_toolbar_workspaces.py tests/ui/test_modeling_toolbar.py -q` → **26 passed**。
- XCB 原生交互：通过 QTest 按下手柄、移动、释放，将绘图、修改、尺寸三条栏分别拖出；确认三栏 `isFloating()`，二维/三维切换同步隐藏/恢复，提交后新草稿保持悬浮，绘图栏通过真实拖动重新停靠。记录在 `native-floating.log`，可重复的隔离脚本为 `native-floating-check.py`。这些是程序驱动的 Qt GUI 检查，未冒充用户人工验收。
- XCB 截图：1400×900、1024×768 二维布局及1024×768 三维布局已查看；小窗口二维画布756×320，按钮和底部操作可见；三维建模栏独立一排。宽度不足时 Qt 原生溢出入口可用。
- 最终布局分行修正后：`QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_toolbar_workspaces.py tests/ui/test_menus_toolbar.py -q` → **27 passed in 55.37s**；四个受影响 Python 文件 `ruff check`、`ruff format --check` 通过，`basedpyright` **0 errors / 0 warnings / 0 notes**。
- 仅验证关联路径，未重复全仓测试。没有修改用户模型文件，运行时设置通过临时 INI 隔离。

## 人工验收步骤

1. 重启新版 GUI；底部命令行/计划应不占空间。“视图 → 命令行/查看待确认计划”可展开；展开后退出并重开仍应默认收起。
2. 新建二维图。绘图、修改、尺寸为三条栏；握住各栏最左侧点状手柄拖出，分别成为浮动栏。如果此前锁定，先取消“视图 → 锁定工具栏”。
3. 拖到工作区四边可停靠，拖到已有栏旁可组合成行，拖到其下可另起一行。工具栏菜单可显隐某一栏或恢复默认布局。
4. 保持一条悬浮、一条侧边停靠，切到三维：二维浮动栏消失、三维建模栏出现；切回二维：草稿及二维布局恢复。完成草图后下一草稿保持相同布局；关闭重开后布局也应保持。
5. 三维建模栏应包含拉伸、旋转、孔、圆角等；主工具栏不再包含这些建模按钮。确认锁定工具栏后均不可拖动，取消锁定后恢复。

工程验证与人工接受分开记录；本记录不宣称全面达到 AutoCAD/Solid Edge 的全部工具栏定制能力。
