# U00 参考、画面与动作基线

初始记录日期 2026-11-04。MyCAD 基础 commit `ba2f53920e78a1f349196e23d3c09e2978389d32`，工作区含大量未提交和未跟踪改动；初始源码与截图是当时的观察，不是干净 commit 的行为结论。2026-11-05 增加了用户提供的 ST10 和 AutoCAD 操作录像取样；用户确认 AutoCAD 2023 与 2025 均可作为验收依据，具体版本和录像覆盖范围见各自证据记录。缺失证据不得视为通过。

## 七组画面登记

| 场景 | 参考及模式 | 参考画面/行为 | MyCAD 当前画面 | 环境信息 |
| --- | --- | --- | --- | --- |
| 首页 | Solid Edge ST10 启动页，不适用有序/同步 | 待采集 | [首页虚拟窗口](u01-start-page-xvfb.png) | ST10 更新号、语言、缩放待核对；MyCAD 为虚拟窗口取证，实机分辨率/缩放待记录 |
| 零件空闲 | ST10 有序；同步另行记录 | [有序零件布局参考](reference-solidedge-st10-ordered-user.png)；[同步空闲及有序录像取样](st10-video-reference/observations.md) | [当前零件空闲](current-part-idle.png) | 同上 |
| 选面 | ST10 有序；同步另行采集 | [有序录像取样](st10-video-reference/observations.md)，同步操作待采集 | [当前选面入口](current-part-select-plane.png) | 同上 |
| 草图绘制/尺寸 | ST10 有序；同步另行采集 | [有序录像取样](st10-video-reference/observations.md)，同步操作待采集 | [当前草图工具](current-part-sketch.png)；历史探针见下 | 同上 |
| 工程图 | ST10 Draft，不套用零件模式 | 已有 [ST10 Draft 录像选段](st10-draft-video-reference/observations.md)；另有 [ST9 工程图录像取样](st9-video-reference/observations.md) | [当前工程图入口](current-engineering-start.png) | ST10 样本为英文，维护包、显示缩放待核对；ST9 单列为独立参考 |
| 二维绘图 | AutoCAD 2023 或 2025 | [2025 启动页](reference-autocad2025-start-user.png)；[2023 录像取样](autocad-video-reference/observations.md) | [当前二维绘图](current-2d-drawing.png) | 更新号、系统缩放、输入法待核对 |
| 二维修改 | AutoCAD 2023 或 2025 | [2023 录像取样](autocad-video-reference/observations.md) | [当前二维修改](current-2d-modify.png) | 同上 |

用户的 Solid Edge 2019 图只可作视觉参考，不是 ST10 依据。有序操作与同步空闲画面已有录像取样，不能互相替代；ST10 同步建模操作仍待取证。用户另提供的 [ST9 同步操作录像取样](st9-video-reference/observations.md)可作为同步操作参考，不能冒充 ST10 证据。`.omo/evidence/st10-3d-review-2026-11-04/probe-results.json` 是旧源码哈希对应的三项自动探针，记录过预览偏差、未完成图元提交、撤销残影；当前代码的后续复验见 U04 进度，人工复验仍单独登记。

## 动作及路由清单（源码盘点）

动作身份以代码中 QAction、命令 ID 或按钮处理函数为准；“有处理”仅表示连接到代码，不代表功能全流程或参考验收通过。下表保留初始源码盘点，并非当前实现状态；后续首页和动作目录实现见 [U01 进度](u01-progress.md)及 [U02 进度](u02-progress.md)。插件运行时贡献仍待 U02/U09 冻结目录时补全。

| 身份/动作 | 文档 | 入口 | 可用条件与处理 | 重复/缺口 |
| --- | --- | --- | --- | --- |
| `act_new` / `act_new_drawing` | 零件 / 独立二维 | 文件菜单；新建也在通用工具栏 | 分别连接 `_on_new_document` / `_on_new_drawing_document`；二维要求 services | 首页四卡片尚无 |
| `act_open`, `act_save`, `act_save_as`, `act_save_all` | 当前/全部文档 | 文件菜单；打开/保存也在通用工具栏 | 各连接生命周期处理；全部保存要求 document_session | 类型路由、守卫需 U01 复验 |
| `act_view_2d` / `act_view_3d` | 二维 / 零件 | 视图菜单及通用工具栏 | 前者连接新建二维文档，后者连接 `_show_3d_workspace` | 名称似视图切换，但二维会新建；U02 必须拆清文档与环境 |
| `act_undo`, `act_redo` | 活动文档 | 编辑菜单、通用工具栏 | 连接 request_undo/request_redo，依状态守卫 | 跨文档与草稿归属需复验 |
| `act_sketch` 和直线/连续线/矩形/圆/圆弧动作 | 零件内草图 | 特征菜单、零件草图菜单及功能区 | services 可用时连接创建或 `_start_part_sketch_tool` | 同一 QAction 复用；工具完整行为待 ST10-S 逐项验证 |
| `feature.box`, `feature.cylinder`, `feature.sphere`, `feature.extrude`, `feature.revolve`, `feature.hole`, `feature.hole_pattern`, `modify.fillet`, `modify.boolean_cut`, `modify.boolean_intersect`, `modify.boolean_bodies`, `modify.body_transform`, `modify.body_pattern` | 零件 | 特征菜单、建模竖栏、零件功能区 | 初始依 plan_draft；经 `_on_toolbar_modeling` 起草，活动零件条件另刷新 | 同一 QAction 在多个入口重复呈现；不等于重复命令 |
| 选择过滤/视图方向/投影/适应窗口 | 零件视图 | 视图菜单，适应窗口也在通用工具栏 | 有对应回调，启用随视口状态 | 运行态、焦点需复验 |
| `act_measure`, `act_screenshot`, `act_delete` | 公共 | 工具/文件/编辑菜单 | 初始化禁用；此处未看到启用的完整用户路径 | 禁用占位，后续逐项查明，不宣称可用 |
| 草图绘制、修改、尺寸工具栏及参数面板 | 独立二维 | `SketchEditor` 三条可移动工具栏和右侧参数 dock | 由 `sketch_editor.py` 连接画布和尺寸状态；各工具各自核验 | 工具逐项动作清单待 U09 完善；不能与零件草图混算 |
| `sheet_action`, `sketch_view_action`, `base_action`, `update_action`, `dxf_action`, `pdf_action`, 删除/取消及标注动作 | 工程图 | `DrawingWorkbench` 工具栏及标注栏 | 根据来源、loaded、busy 和选择动态启用；有各自连接 | 创建图纸与来源路径、保存/更新须 DRAFT 全链复验 |
| `act_show_ai`, `act_view_plans`, `act_show_cli` | 公共辅助面板 | 智能体/视图菜单 | 连接面板；依 services 等状态启用 | AI 连接状态和真实能力另验，不以面板存在证明对话可用 |

当前代码补充盘点（2026-11-05）：`ActionCatalog` 已登记首页、文件生命周期、撤销/重做、视图入口、零件草图和内置建模动作，菜单及其他入口复用同一 QAction。插件贡献通过 `_register_plugin_actions` 登记；不在桌面计划支持范围内的插件动作禁用并显示原因。独立二维的工具按钮仍由其自身工作台管理，不能据此声称所有环境动作均已接入目录；插件动态卸载和完整人工交互尚需分别验证。

## 验收映射

| 组 | 责任包与自动验证候选 | 人工取证 |
| --- | --- | --- |
| HOME | U01：新增 `tests/ui/test_start_page.py`；`test_document_session.py`, `test_document_save_session.py` | 冷启动四入口、三类新建、取消、失败打开、返回和最后关闭；录像及文档数/脏状态 |
| COMMON | U02/U12/U13：`test_menus_toolbar.py`, `test_workspace_tabs.py`, `test_legacy_layout_startup.py`、保存测试 | 焦点/中文输入法、活动命令、迁移、各环境往返与 DPI；各配置截图及重启记录 |
| ST10-UI | U03/U04：`test_menus_toolbar.py`, `test_command_palette.py`, `test_workspace_tabs.py` | 有序/同步参考与 MyCAD 布局、导航、命令条在三种窗口宽度对照 |
| ST10-S01–S15 | U04–U08/U11/U13：`test_part_sketch_workbench.py`, `test_modeling_interaction.py`, `test_picking.py`, `tests/geom/test_m2b_associated_constraints.py` | 按 ST10 基线逐工具/模式录制，关联失败和重开单独记录；不以单一测试覆盖整行 |
| ACAD-2D | U09/U13：见独立 AutoCAD 验收表 | 固定配置截图与绘图→修改→标注→保存/DXF 录像 |
| DRAFT | U10/U13：`test_drawing_start.py`, `test_drawing_templates.py`, `test_drawing_views.py`, `test_drawing_updates.py`, `test_drawing_annotations.py`, `test_drawing_pdf.py` | 图纸→模型视图→标注→源模型更改→更新→保存重开/输出全链录像 |

所有组参考核对、工程实现、自动验证和用户验收分别登记；本文件未执行这些场景，均不得标记通过。

## 本次自动检查记录

2026-11-04 执行 `uv run pytest tests/ui/test_workspace_tabs.py tests/ui/test_drawing_start.py tests/ui/test_menus_toolbar.py -q`，中途人工中断：20 passed、1 failed，其余未运行完。失败为 `test_empty_model_explains_source_and_can_navigate_to_sketch`，点击草图按钮后实际 `active_workspace == "model"`，测试预期 `"sketch"`；Qt 同时警告当前平台不支持 QOpenGLWidget。原因未经诊断，不能据此判定是环境或产品缺陷，也不代表 U00 人工验收。工作区原有 UI 文件已修改，本包未改应用代码。

## 截图取证条件与限制（2026-11-04）

当前截图由 [capture_current.py](capture_current.py) 在隔离的 Xvfb/X11 1440×1000、窗口 1366×900、Qt xcb、中文界面、默认缩放（未实际测量系统 DPI）生成；QSettings 定向到 `/tmp/mycad-u00-qt-settings`。脚本直接调用 UI 和会话接口，不代表鼠标逐步操作或用户验收。工程图图像是空模型来源提示，不是已建图纸；选面图像是选面入口状态，不证明真实实体面拾取。最初使用 16×10 mm 矩形时，草稿有 1 个图元和 1 条渲染曲线，但角点投影至视口外；改为 2×1 mm 后，图中显示矩形，角点投影至视口内。该截图仅证实此取证场景下可见，真实 GPU、鼠标操作和其他缩放仍需复验。首页尚不存在，故无对应当前截图。

截图当时源码 SHA-256：`main_window.py` d7c025f4a667333da038732ad3b1d1b9dd76cbab81649fe3ba35cebbbb988aa6；`part_sketch_workbench.py` fe52d8b46a3cd6e4e7dfbf3e760558853460e8c1ce7aa53b615f1384870bd52a；`sketch_editor.py` 59f68563e677090f9eb16ab76dc3d53873a7c06acbfd436e150c6a1cdbea6ef3；`drawing_workbench.py` 1f4172970ab1fed1a7c529fbf650baf5cbe70b2325724f39fcaa71003d84c5d4。首次采集时退出前存在未取消草稿，进程未正常结束并被终止；脚本后来在截图后取消草稿，重新采集退出码为 0。QSettings 目录为隔离目录，但复用时布局状态可能发生变化，不代表首次安装默认布局。

## 二维动作展开（源码）

| 动作身份 | 入口/状态 | 处理与局限 |
| --- | --- | --- |
| `选择元素`, `直线`, `多段线`, `矩形`, `多边形`, `圆`, `圆弧`, `样条曲线` | 独立二维绘图工具栏，当前工具可选中 | `tool_buttons` 切换 `tool_combo`，后由画布工具状态处理；样条提示至少四控制点 |
| `修剪`, `延伸`, `分割` | 独立二维修改工具栏，当前工具可选中 | 同样经 `tool_combo` 切换画布工具；实际边界和撤销需逐项验 |
| `move`, `copy`, `rotate`, `mirror`, `offset`, `linear_array`, `circular_array` | 修改工具栏；初始禁用，需选择图元等条件 | 连接 `_start_transform`；数值变换还有参数面板入口，状态与结果需复验 |
| 智能、水平、垂直、对齐、角度、半径、直径、弧长、连续、基线、坐标 | 尺寸标注工具栏 | 以尺寸控制器为入口；普通标注与驱动语义和旧档兼容尚待专项确定 |
| 图层管理、显示网格、捕捉、网格捕捉、正交 | 二维画布上方控制栏 | 独立控件，不可推定极轴追踪或 AutoCAD 所有状态栏行为已存在 |

## 工程图入口测试复核

同一失败单测用 `QT_QPA_PLATFORM=xcb uv run pytest tests/ui/test_drawing_start.py::test_empty_model_explains_source_and_can_navigate_to_sketch -q` 单独运行仍失败（1 failed）；排除仅因 offscreen 平台警告导致的简单解释。源码路径为工程图按钮发 `sketch_requested` → 切换 sketch 标签 → `_on_workspace_changed` → `_on_sketch_start`；当绑定文档是 part 时后者调用 `_show_3d_workspace` 并创建 `PartSketchWorkbench`。旧测试预期独立 `SketchEditorDialog` 和 sketch 标签，与现行零件草图三维画布行为不一致。工程图按钮是否应转向独立二维或零件草图须结合 U01/U10 来源流程确定，本次未改产品或测试，也未宣称行为已通过需求验收。

同一 X11 后端下，`QT_QPA_PLATFORM=xcb uv run pytest tests/ui/test_part_sketch_workbench.py::test_part_entry_uses_independent_workbench_and_guards_draft tests/ui/test_part_sketch_workbench.py::test_2d_entry_opens_separate_sketch_workspace -q` 结果 **2 passed**，支持上述两条入口目前分离的判断；不覆盖工程图按钮的期望或人工验收。

2026-11-05 后续复核：当前 `test_drawing_start.py` 已按独立二维与零件草图区分后的行为核对该入口：对零件文档从工程图进入零件草图工作台，再返回工程图；独立工程图的模型来源使用另行选择流程。该测试与首页、最近文档和工作区标签合并运行 **37 passed**（Xvfb/xcb、软件 OpenGL）；这是当前代码的自动回归结果，先前失败记录保留为历史，不作为当前未解决失败。工程图来源流程的人工验收仍单独待核对。

## 用户提供的 AutoCAD 2025 界面参考

[启动页参考图](reference-autocad2025-start-user.png)由用户提供，PNG 1611×993，SHA-256 `c46b22d3e36a31c7999b1168a89d7fef88c9bc3ec112bafa0d71b798bfd2efc9`。画面显示中文 AutoCAD 2025 标题、顶部快速工具区和功能区、文档标签、启动页的打开/新建和最近项目；可用于辨识层级与中文标签。它显示启动页而非绘图区，也无法单凭画面验证工作区名、显示缩放、更新号或操作行为。用户称其经典模式，保留这一描述，不据此假定官方预设名称或工作区配置。整体首页仍依统一设计的 Solid Edge 四入口要求，截图仅作 AutoCAD 页面参考。

## 用户提供的 Solid Edge 界面参考

[界面参考图](reference-solidedge-ui-user.png)由用户提供，PNG 1280×720，SHA-256 `2d97b871cdeb46c3f6181984be64b785b78e38a7eec6ced6c4fa2885fafbe73c`。画面为带“Siemens AG 2017”字样的中文说明页，标注主菜单页、工具箱、动态工具条、资源查找器和工作区；可作为 U03 功能区、导航、画布及 U04 命令反馈的视觉层级参考。画面展示摩托车模型、画布内浮动工具条、上下文菜单和右侧树，不能据此推定其具体文档类型、版本/维护包、有序或同步模式，也不能证明零件草图和工程图操作。ST10 精确核对及七组对应画面仍待取得。

## 用户提供的 Solid Edge ST10 有序零件参考

[ST10 有序零件截图](reference-solidedge-st10-ordered-user.png)由用户提供，PNG 1280×979，SHA-256 `35fe99928d89abbb904005c7e00702c1eb0aaca98dae7d6b8af099e9d5be2874`。标题显示 `Solid Edge ST10 - Ordered Part`，关于窗口显示版本 `110.00.00.107 x64`，界面为英文；维护包名称、操作系统、屏幕缩放及配置未标明。可见 Home 页的 Sketch、Extrude、Cut、Revolve、Hole、Round 等组，左侧有序特征树、文档标签、底部提示栏和视图控制。图中为已有特征的模型，帮助面板及关于窗口遮挡部分视口；不是完整空零件、选面或草图画面。截图用于 U03/ST10-UI 的有序模式可见布局核对，不证明控件的动态状态、快捷键或命令操作通过；同步模式与 ST10-S 各操作仍须另行取证。

## 用户提供的 Solid Edge 三维 PMI 场景

[PMI 场景参考图](reference-solidedge-pmi-user.png)由用户提供，PNG 1920×1080，SHA-256 `7e31047f24dce5c76a0e185b824f3c3b2b5cba543fb1a077909d70c0adf04aa6`。标题显示英文 Ordered Part，PMI 标签被选中；画面可见左侧 PathFinder 的 PMI 及模型视图树、中央模型及尺寸标注、右侧 Inspector 面板、顶部多文档标签和底部提示/视图控制。可参考三维界面层级、标注可读性及按需面板；图片未标明软件具体版本、维护包或系统缩放，不作为 ST10 特定操作依据。图中的 PMI 是模型产品制造信息场景，不能等同零件草图的驱动/参考尺寸或工程图标注，也不能证明任何尺寸可编辑或有关联语义。完整 PMI 属 U14 后续专项，本轮不以图片引入空功能页或宣称已有 PMI 能力。

## 用户提供的操作录像链接（待核对）

2026-11-05 用户提供 [Solid Edge 操作录像](https://www.youtube.com/watch?v=coK0gowtyps) 与 [AutoCAD 二维操作录像](https://www.youtube.com/watch?v=WvtqAYp0NKE)。浏览器播放超时、网页读取被限流；直接读取视频页面元数据得到前者标题为 “Solid Edge ST10 - Tutorial”，作者 László Toldi，时长 730 秒；后者标题为 “2D Drawing in AutoCAD | Step by Step Tutorial for Beginners | AutoCAD 2025 Practice Exercise”，作者 DESIGNER，时长 171 秒。以上版本仅为标题信息，尚未核实画面中的软件版本、Solid Edge 模式或具体操作时点。待能够播放后逐项记录时间戳和可见动作，再对照对应 MyCAD 场景；链接本身不能替代实机或用户验收。

补充：从视频页面提供的低分辨率时间轴预览观察到，Solid Edge 录像包含平面草图和弯管状三维模型，但 160×90 单帧不足以辨认模式和准确命令。AutoCAD 录像约 00:00–00:34 可见左侧图纸参考与右侧深色绘图区、同心圆、光标附近浮动输入以及底部命令行；约 01:48–02:04 可见多个圆、连接线及上下文菜单。预览按约两秒抽帧，无法证明具体输入值、完整步骤、快捷键或最终图形约束；时间为预览近似值。需完整播放核实，不能据此把任何验收项勾选通过。

用户随后提供本地 Solid Edge 录像，已读取高清静帧：本地录像 00:10 的标题与树明确显示 ST10 同步零件，00:20 切为有序零件，后续抽样中的草图、尺寸、实体和孔主要属于有序环境。截图及局限见 [录像取样观察](st10-video-reference/observations.md)。同步部分目前只确认空闲界面，未证明同步操作行为；录像不是本项目用户验收。

用户随后提供本地 AutoCAD 录像，高清画面标题明确显示 `Autodesk AutoCAD 2023`，与原视频标题及文件名中的 2025 不一致。已按 2023 参考登记[取样观察](autocad-video-reference/observations.md)，不能用于证明 2025 特有行为；既有用户提供的 2025 启动页截图仍单独保留。

2026-11-07 扩充该录像的本地时间码取样至 01:00、01:30、01:50、02:30、02:50，并在观察记录中关联 MyCAD 对应命令、测试与缺口。02:30 的 `CIRCLE` TTR（两切点加半径）尚无 MyCAD 等价圆命令；自动切点捕捉不是等价实现。此为选段取样，未完整观看录像，AutoCAD 实机对照和用户验收仍待完成。

## 2026-11-05 工程图旧入口测试复核

原失败来自测试仍要求旧二维草稿窗口：当前零件草图在模型视口使用 `PartSketchWorkbench`。测试已改为检查点击入口后进入模型环境并启动该工作台，退出后可返回工程图；`tests/ui/test_drawing_start.py` 在 Xvfb/xcb、软件 OpenGL 下 3 项通过。此结果只验证当前产品路由，未替代 U10 对独立工程图来源流程的验收，也未完成 ST10 实机对照。

2026-11-07 ST10/ST9 模式核对：重核本地 ST10 录像在 00:10 的同步空闲、00:15 模式选项和 00:17 有序标题/树，新增裁剪帧；将当前登记的 ST10 后续草图、尺寸、孔及阵列样本逐项与 MyCAD 代码、自动测试和人工证据状态对应。ST9 V01–V09 仍单独作为同步模式参考，V10/V11 为 Draft；没有将它们标成 ST10 证据。详情见 [ST10/ST9 对照矩阵](st10-st9-crosscheck.md)。完整视频复核、同步操作实机对照和用户验收未完成。

2026-11-07 独立二维动作补充盘点：依据当前工作区源码，记录工具栏、命令栏、参数页、尺寸及状态控件的入口、守卫、关联测试和已知边界，见[独立二维动作清单](u00-drawing2d-actions-2026-11-07.md)。该清单只覆盖独立二维；公共、插件、零件草图和工程图动作仍须分别核对，U00 保持未完成。

2026-11-07 工程图动作补充盘点：将 ST9 V10/V11 Draft 的入口、视图布局、尺寸、来源变更和更新反馈按本地录像时间码映射到 MyCAD 工作台、自动测试及功能差异，见[工程图动作盘点](u00-drawing-actions-2026-11-07.md)。ST9 片段只作 Draft 参考；ST10 Draft 来源片段、同条件实机对照和用户验收待办保持开放，U00 未完成。

2026-11-07 ST10 全片候选筛查：对 714.31 秒本地录屏以 10 秒为步长抽帧检查工作区标题/功能区，样本显示同步空闲、Sketch 与 Ordered Part，未见 Draft；此结果是取样筛查，完整逐段观看及 ST10 实机对照仍待完成。筛查边界见[ST10 观察记录](st10-video-reference/observations.md)。

2026-11-07 后续：用户新增 Draft 视频目录。01 号录像标题明确显示 ST10 Draft，已有新建/图纸设置、模型选择、视图、标注和视图过期警告的时间码与 MyCAD 映射；同目录亦有 2019、2021、2024 画面，按实际版本分列。见 [ST10 Draft 观察及清单](st10-draft-video-reference/observations.md)。此前 714.31 秒筛查结论仅指旧的零件录屏；同条件实机对照与用户验收仍待完成，U00 未完成。
