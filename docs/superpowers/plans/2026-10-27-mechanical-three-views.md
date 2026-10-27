# MyCAD 机械三视图与三工作区 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户于 2026-10-27 确认实施：先提交基线，再完成 T0；通过后继续后续阶段。执行前读取配套设计和最新 AGENTS.md。

**Goal:** 在“平面草图｜工程图｜3D图”常驻画布页中，完成当前零件的关联三视图、基础测量标注及按比例出图。

**Architecture:** 在同一 part 文档中分离草图、实体、工程图领域对象；工程图持久操作经 CommandBus 重放，投影缓存为派生数据。geom 内完成精确 HLR 与来源解析，core 提供纯数据契约，UI 和输出共同消费冻结 DrawingScene。首版不引入外部文件关联。

**Tech Stack:** Python、build123d==0.11.1、cadquery-ocp-novtk>=7.9.3.1.1,<7.9.4、PySide6、ezdxf、pytest；沿用 uv.lock，不以依赖升级代替适配验证。

**Spec:** [机械三视图评估与设计](../specs/2026-10-27-mechanical-three-views-design.md)。日期 2026-10-27；以下全部是拟实施事项，勾选只在实际验证后进行。

## Global Constraints

- 用户已要求草图/工程图分离及三个画布 Tab；同文件保存、第一角默认、工程图测量语义、首版范围为建议默认值，已随本 Plan 获用户确认。
- 当前 MyCAD 原生零件的已提交实体为源；多实体一起计算遮挡；不自动提交正在编辑的草图。
- 草图新尺寸默认驱动；工程图默认关联测量，不反向修改模型。
- 第一角主/俯/左为建议默认，支持第三角及左右侧视；A4/A3 横纵纸张，标准比例和可编辑简式标题栏。
- core 禁 CAD 后端/numpy，Qt 只在 ui，CAD 后端只在 geom，app.py 为组合根。禁止类型抑制、逐文件 lint 豁免。
- 模型/图纸修改只能经 Bus；计算派生投影不追加历史。保留审计六字段、amendments 和原子存档。
- 优先 v3 part + 新命令参数；drawing2d 不扩充实体/工程图命令白名单。旧文件打开不写回。
- 图中交互、右侧可浮动页、底部共享信息/CLI/未连接 AI/计划页；无独占式参数表单。
- 不纳入本批：外链工程图、装配、剖视、局部放大、断裂、GD&T、公差配合、螺纹规范画法、BOM、自动全标注。
- 保留现有脏工作树；执行前记录基线，分任务只暂存本任务差异。不得打包提交前序功能或重置它们。

## Review Focus

1. 相同形状重复孔/对称边产生多候选：标为 ambiguous，绝不静默串尺寸（T0/T6）。
2. 切页时存在抓鼠标、未提交尺寸或浮动面板：保留草稿并释放输入捕获，不从隐藏页误收快捷键（T4）。
3. 工程图命令插入模型历史：几何身份/源模型指纹不应改变，历史检查点仍可回放（T2）。
4. 同一 session 中连续换方向再撤销：晚到结果不能覆盖当前图纸（T5）。
5. 1:2 图纸、中文标题、椭圆/样条、已有目标文件：实际导出保比例、无缺字/漏线，失败不破坏原文件（T7）。

## 文件与接口边界

| 文件（新增，除注明修改） | 单一职责 |
|---|---|
| `src/mycad/core/drawing.py` | Sheet/View/Annotation/State、纯数据校验与命令 reducer |
| `src/mycad/core/drawing_references.py` | 持久语义引用、解析状态 DTO，不携带 OCP 对象 |
| `src/mycad/core/drawing_projection.py` | 投影请求/精确曲线/不可变结果/纸张场景及能力 Protocol |
| `src/mycad/geom/drawing_projection.py` | HLR、曲线分类、模型来源证据、曲线转换 |
| `src/mycad/geom/drawing_references.py` | 有界语义匹配、唯一性判断、失关联诊断 |
| `src/mycad/geom/kernel.py`（修改） | 组合 drawing 状态、路由命令、reset/候选复制/检查点接入 |
| `src/mycad/builtin_commands/drawing_specs.py` | 工程图命令及参数 schema；由现有注册入口汇入 |
| `src/mycad/app.py`（修改） | 投影/场景构建能力桥接，保留 AppServices 既有契约 |
| `src/mycad/ui/workspace_tabs.py` | 三个常驻页与工作区路由，避免散布 centralWidget 身份判断 |
| `src/mycad/ui/drawing_workbench.py` | 工程图右侧属性页、图纸选择、上下文动作 |
| `src/mycad/ui/drawing_canvas.py` | 纸张场景显示、选取、坐标变换 |
| `src/mycad/ui/drawing_tools.py` | 放置/拖动/标注状态机与临时预览 |
| `src/mycad/ui/drawing_pdf.py` | QPdfWriter 矢量纸张输出与同源预览；Qt 留在 ui |
| `src/mycad/formats/drawing_export.py` | 显式工程图 DXF 输出 API；不新注册同优先级 .dxf provider |
| `src/mycad/ui/main_window.py`、`sketch_editor.py`、`execution.py`（修改） | 接入上述组件、草稿生命周期及计算路由 |

公共契约由 T1 定义，T0 仅探针，不冻结未经验证的 OCCT 来源方案：

- `WorkspaceId = Literal['sketch', 'drawing', 'model']`，仅 UI 路由标识，不作授权凭证。
- `DrawingState`：sheet/view/annotation 以持久 UUID 标识；不含缓存、Qt 或后端对象。
- `DrawingOperation`：已验证的工程图命令 id 与类型化参数联合；`apply_drawing_operation(state: DrawingState, operation: DrawingOperation) -> DrawingState`。
- `DrawingProjectionRequest`：view_id、source=current_part、右/上/法向正交基、显示策略、模型指纹、请求代次。
- `DrawingProjectionPort.project_drawing(request: DrawingProjectionRequest) -> ProjectionResult`；BuildKernel 实现，UI 经注入的 Protocol 消费，不导入 geom。
- `ProjectionResult`：source_fingerprint、view_id、generation、精确局部曲线和来源证据、诊断；不含纸上平移和视图比例。
- `resolve_reference(reference: DrawingGeometryReference, result: ProjectionResult) -> ReferenceResolution`；状态为 resolved/orphaned/ambiguous，只有 resolved 携带唯一几何。
- `build_drawing_scene(state: DrawingState, sheet_id: UUID, projections: Mapping[UUID, ProjectionResult]) -> DrawingScene`：纯纸张合成，结果包含页尺寸、转换后的几何、纸上文字/线型和阻止出图的问题。
- `export_drawing_dxf(scene: DrawingScene, target: Path) -> None` 与 `export_drawing_pdf(scene: DrawingScene, target: Path) -> None`；先校验冻结场景再原子写入。

## T0 实测裁定（2026-10-27）

详见 [.omo/evidence/mechanical-three-views/probe.md](../../../.omo/evidence/mechanical-three-views/probe.md)。QThread 直接 HLR 未通过250ms UI门槛；spawn进程通过。T3/T5 必须采用常驻进程、异步预热、BREP快照及中性DTO、版本匹配和资源清理。冷启动时明确显示准备中，不计入预热后3s计算目标；正式DTO全程性能仍在T3验收。追加4–6人日，合计38–60人日。

## 实施顺序与投入

| 包 | 产出 | 依赖 | 估计人日 |
|---|---|---|---|
| T0 | HLR、引用、线程、历史接入探针及 go/no-go | 无 | 2–4 |
| T1 | 工程图领域与纯数据契约 | T0 | 3–5 |
| T2 | 命令、重放、存档 | T1 | 4–6 |
| T3 | 精确投影适配 | T0/T1 | 5–8 |
| T4 | 三个常驻画布页与基础放置 | T1/T2 | 5–7 |
| T5 | 对齐/句柄/更新状态 | T2/T3/T4 | 4–6 |
| T6 | 基础标注与引用修复 | T3/T5 | 5–8 |
| T7 | 真实纸张 DXF/PDF | T5/T6 | 3–5 |
| T8 | 跨工作区验收与文档 | 全部 | 3–5 |

合计 **34–54 人日**，一名熟悉项目工程师约 7–11 工作周；不等同代理运行时间。T0 后重估，独立工作进程或扩大拓扑命名范围需另列工作。T2/T3 可在契约稳定后独立开展，但合入前必须共同验证。

### Task 0: T0 — 先证明几何与架构路径可用

**Files:** 新增 `tests/geom/test_drawing_projection_probe.py`、`tests/ui/test_drawing_execution_probe.py`；证据 `.omo/evidence/mechanical-three-views/probe.md`。必要原型只在 geom 测试合法边界或临时实验文件，不接产品按钮。

**Interfaces:** 输入当前精确 Part 和显式坐标基；输出探针报告、支持曲线/来源策略、实际耗时与线程证据。

- [x] 写数值断言：不对称阶梯块+偏心孔的正反/左右不能镜像混淆；法兰四孔圆心距离和直径正确；双实体遮挡边不错误可见。
- [x] 运行 `uv run pytest tests/geom/test_drawing_projection_probe.py -q`，记录基准失败而非跳过未支持曲线。
- [x] 用已安装 HLR 精确接口验证 visible/hidden/tangent、圆柱轮廓来源、椭圆及有理样条；检查 BuildCurves3d 等必要修复。明确轮廓来自面，不能伪造原始边引用。
- [x] 探针验证改长度/改孔径后唯一重绑定、删除和重复孔后拒绝歧义。至少记录一个成功、一个 orphaned、一个 ambiguous 案例及来源证据，不接受最近边兜底。
- [x] 验证非几何历史项进入 reset/replace_state_from/预览不会改变 BodyOrigin；确认 v3 command params 足以保存图纸，无需添加顶层字段。
- [x] 记录参考硬件、边/面数、p50/p95、内存和 UI 心跳；运行 `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_drawing_execution_probe.py -q` 并在真实桌面观察一次。100 ms 心跳，>250 ms 停顿诊断；≤1000 边三视图 ≤3 s 为待审定目标。
- [x] 写 go/no-go：精确曲线和有界引用通过才能进入 T1/T3；若 GIL 阻塞严重，先补进程隔离设计与预算，不把 QThread 包装当作解决。报告不满足条件的样本和原因。

### Task 1: T1 — 领域对象、坐标和继承规则

**Files:** 新增三个 core/drawing* 文件（见上表）、`tests/core/test_drawing_model.py`、`tests/core/test_drawing_coordinates.py`。

**Interfaces:** 产出上述 DTO/reducer/场景接口及不可变值对象；精确曲线联合含 line/arc/ellipse/bspline（degree、knots、multiplicities、weights）。

- [x] 写 RED 测试 `test_first_and_third_angle_layout`、`test_scale_does_not_change_measurement`、`test_parent_cycles_and_cross_sheet_links_rejected`。断言第一角 top 在下、left 在右，第三角相反；80 mm 在 1:2 纸上 40 mm；非法父子关系失败且输入状态不变。
- [x] 运行 `uv run pytest tests/core/test_drawing_model.py tests/core/test_drawing_coordinates.py -q`，确认缺失实现导致失败。
- [x] 实现 Sheet/View/Annotation/State 与引用 DTO，正交基拒绝零向量/共线输入；纸张 A4=210×297、A3=297×420 mm，旋转交换宽高；比例严格正且有限。
- [x] 实现 reducer 和父子有效属性解析：存储继承标志，解除/恢复对齐显式可逆；更换投影法只通过明确重排操作作用于既有视图。
- [x] GREEN 跑同组测试及 `uv run pytest tests/test_layering.py -q`；仅对新增 core 文件执行 lint/format/type 检查。交付纯数据契约，不加入 Qt/CAD 导入。

### Task 2: T2 — 命令、事务、历史和存档

**Files:** 新增 `builtin_commands/drawing_specs.py`、`tests/core/test_drawing_commands.py`、`tests/core/test_drawing_archive.py`、`tests/geom/test_drawing_state.py`；修改 specs/defs 注册入口、geom/kernel.py、core/persistence.py 与必要 schema 选择路径、app.py。

**Interfaces:** 注册 `drawing.sheet.create/update/delete`、`drawing.view.create/update/delete`、`drawing.annotation.create/update/delete`（首版命令版本 1）；参数 schema 引用 T1 数据，不收任意可执行代码。沿用 Bus execute/execute_batch。一组放置/更新使用单条命令的 views 数组，保证一个历史项和一次撤销；execute_batch 保证失败回滚。

- [x] RED：`test_group_creation_is_atomic_and_replayable` 在第二子视图失败后状态/历史完全回滚；`test_layout_command_keeps_geometry_identity` 比较前后几何指纹与有效选择；`test_part_archive_roundtrip_and_old_audit_preserved` 检查六字段、amendments；`test_drawing2d_rejects_engineering_commands`。
- [x] 运行 `uv run pytest tests/core/test_drawing_commands.py tests/core/test_drawing_archive.py tests/geom/test_drawing_state.py -q`，记录预期失败。
- [x] BuildKernel 组合 DrawingState、分离文档/几何/布局 revision；工程图命令只改图纸状态。reset、重放、候选 install、事务快照全部包含 DrawingState，图纸移动不创建新实体来源。
- [x] 接入独立非几何历史检查点，确保 state_id/ordinal 查询仍有效；禁止通过过滤历史后重编号破坏引用。
- [x] 新工程图 part 以 v3 存档，旧 v1/v2 在保存含新命令的文档时升级；打开不写回。仅新命令 params 保存对象，缓存不入档；未知命令版本给出明确错误。
- [x] GREEN 跑同组；追加既有 persistence/undo/app 候选加载相关 scoped 测试。提交前检查仅本包文件差异，保留用户前序修改。

### Task 3: T3 — 精确投影与可追踪曲线

**Files:** 新增 `geom/drawing_projection.py`、`tests/geom/test_drawing_projection.py`；修改 kernel.py/app.py 的能力接线。

**Interfaces:** 实现 `DrawingProjectionPort.project_drawing`；用 T1 request/result，来源匹配依 T0 已证明策略，不自行扩大承诺。

- [x] RED：`test_asymmetric_three_views_have_expected_coordinates`、`test_hole_occlusion_and_cylinder_silhouettes`、`test_two_solids_occlude_each_other`、`test_ellipse_and_rational_curve_not_flattened`、`test_tangent_policy_does_not_remove_sharp_edges`。
- [x] 运行 `uv run pytest tests/geom/test_drawing_projection.py -q`，失败必须由数值/拓扑断言体现，不能只保存截图。
- [x] 在 geom 中计算整件 HLR 并分类；复用必要曲线修复，过滤零段/接缝并处理重复；源模型到局部坐标同基准，禁止各视图独立居中。
- [x] 将精确线、圆/弧、椭圆和完整有理样条转换为 DTO；超出表达范围返回诊断，不能静默降为折线。
- [x] 缓存以模型内容指纹+来源+基方向+几何策略/内核版本索引；纸上移动/比例不得进 HLR 缓存键。空模型可显示空页，但创建视图明确失败。
- [x] GREEN 跑同组和 T0 几何回归，输出数值及定向截图证据；按 T0 审定容差验收。

### Task 4: T4 — 三工作区与图纸放置

**Files:** 新增 `ui/workspace_tabs.py`、`drawing_workbench.py`、`drawing_canvas.py`、`drawing_tools.py`、`tests/ui/test_workspace_tabs.py`、`tests/ui/test_drawing_views.py`；修改 main_window.py/sketch_editor.py/workspace_console.py 的接入点。

**Interfaces:** `WorkspaceTabs.activate(workspace: WorkspaceId) -> None`、`active_workspace: WorkspaceId`；`DrawingCanvas.set_scene(scene: DrawingScene) -> None`。原二维/三维 QAction 委托 Tab 切换；保留旧 active_sketch_dialog 等兼容入口。

- [x] RED：`test_three_pages_keep_identity_and_draft` 切三页后草图草稿/选择/缩放/相机不变；`test_switch_releases_capture_and_hides_inactive_floating_dock`；`test_global_undo_does_not_edit_hidden_draft`；`test_drawing2d_does_not_offer_solid_projection`。
- [x] 运行 `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_workspace_tabs.py tests/ui/test_drawing_views.py -q`，确认失败。
- [x] 建立三个常驻页，重用右侧浮动功能区和共享控制台。枚举 main_window.py 所有 `centralWidget()` 身份判断，逐一改为明确工作区路由，覆盖保存、撤销、相机、选择、快捷键和工具菜单。
- [x] 实现 enter/leave：释放抓鼠标、暂停预览、保留未提交草稿；切回时来源已变则提示重选，不偷偷提交或丢弃。新建/打开文档按现有未保存确认路径切换全部页的文档上下文。
- [x] 右侧设置纸张、标题、第一/第三角、比例、基准方向；预览在画布跟随鼠标，单击定位，Enter 通过一个事务提交整组，Esc 撤销整组临时预览。
- [x] GREEN 跑同组及现有 toolbar/workspace_console/草图关闭回归；真实桌面验证窄窗与浮动面板，截图说明画布空间。草图 DIM→0 工具切换既有规则仍通过。

### Task 5: T5 — 视图句柄、对齐与更新

**Files:** 修改 drawing_tools.py/drawing_workbench.py/drawing_canvas.py/execution.py；新增 `tests/ui/test_drawing_grips.py`、`tests/ui/test_drawing_updates.py`。

**Interfaces:** 视图拖动生成 T2 update 操作；后台通过常驻 spawn 进程实现 ProjectionPort 并返回冻结结果，应用结果同时匹配 session、source_fingerprint、view_id、generation。

- [x] RED：`test_parent_move_keeps_children_aligned`、`test_child_move_is_axis_constrained`、`test_scale_override_and_restore`、`test_stale_same_session_result_is_discarded`、`test_delete_view_subtree_is_one_undo`。
- [x] 运行 `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_drawing_grips.py tests/ui/test_drawing_updates.py -q`，确认失败。
- [x] 实现位置/等比比例/解除对齐句柄，拖动全程只预览，松开提交一次；纸张缩放不修改实体，不重算 HLR。
- [x] 定义视图 clean/stale/updating/failed 派生状态，模型变更后安排更新；忙时合并到最新请求，不丢失最后一次更新需求，不插队修改正在计算的模型。旧结果丢弃，失败保留上一版本并标过期。
- [x] 删除父视图时预览子树及关联标注影响，确认后一个事务删除；undo 恢复全部。取消计算只停止接收结果，UI 不谎称已物理中断线程。
- [x] GREEN 跑同组并复测 T0 心跳。整组生成/拖动/取消/更新能通过 CLI 调用相同命令能力，不为 AI 另建写模型后门。

### Task 6: T6 — 关联标注和失关联修复

**Files:** 新增 `geom/drawing_references.py`、`tests/geom/test_drawing_references.py`、`tests/ui/test_drawing_annotations.py`；修改 drawing_tools.py/canvas.py 及 T1 场景合成。

**Interfaces:** 实现 `resolve_reference`，复用草图文字/箭头布局组件但输出 DrawingAnnotation；标注保持 DIM 层和纸上样式。

- [x] RED：`test_length_and_hole_diameter_updates_keep_correct_anchor`、`test_duplicate_holes_are_ambiguous_not_nearest`、`test_deleted_anchor_is_orphaned`、`test_dimension_value_ignores_paper_scale`、`test_ellipse_rejects_circle_dimension`。
- [x] 运行 `uv run pytest tests/geom/test_drawing_references.py -q` 和 `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_drawing_annotations.py -q`，确认失败。
- [x] 实现有界语义证据解析；运行期 ID 不入档，ordinal/index 不作最终身份。只有唯一匹配才重新附着；引用删除/多候选保留文字位置并显示原因。
- [x] 实现水平/垂直/对齐、真实圆半径/直径、两直线角度、中心线/中心标记。线性测量取视图未缩放局部坐标，投影长度与空间真长明确区别。
- [x] 图中拖文字、双击编辑精度/表达、选新几何重附着均经 T2 命令；不允许通过输入虚假尺寸覆盖测量值，不修改实体或草图 driving 默认。
- [x] GREEN 跑同组和 T2 重放/存档测试；重复孔、孔消失、改长度后人工检查警示，导出前问题清单能定位具体标注。

### Task 7: T7 — 同源纸张预览与 DXF/PDF

**Files:** 新增 formats/drawing_export.py、ui/drawing_pdf.py、`tests/formats/test_drawing_export.py`、`tests/ui/test_drawing_pdf.py`；修改工作区导出入口。

**Interfaces:** 使用 T1 `build_drawing_scene` 和两个显式 export 函数。DXF 不改变现有单草图 provider 行为；PDF 首版使用 ui 内 QPdfWriter，headless PDF 不在本包承诺。

- [ ] RED：`test_dxf_sheet_blocks_scale_and_units`、`test_export_matches_frozen_scene`、`test_invalid_scene_preserves_existing_file`、`test_pdf_media_box_and_vector_content`、`test_chinese_title_and_curve_output`。
- [ ] 运行 `uv run pytest tests/formats/test_drawing_export.py -q` 和 `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_drawing_pdf.py -q`，确认失败。
- [ ] DXF 视图局部真实 mm 建块、纸空间按比例插入；纸张图框、标题、线宽、字高及标注用纸上 mm。提供 visible/hidden/tangent/center/DIM 线层映射，显式保留精确椭圆和样条。
- [ ] PDF 使用冻结 DrawingScene 矢量绘制到正确 MediaBox；采用可用中文字体并验证字符，禁止截图输出。预览同一输出场景/实际字节，不自动 fit 改输出比例。
- [ ] clean 且无失关联/缺失几何才允许最终出图；生成临时文件，完整成功后替换目标。标明 DXF 是静态交付，不宣称保存 AutoCAD VIEWBASE/跨软件关联。
- [ ] GREEN 跑同组；解析 DXF 数值验证 80 mm 在 1:2 纸上 40 mm、尺寸文本 80；纸上定位目标≤0.05 mm。外部查看器人工核对 DXF/PDF 线型、中文、页尺寸和打印实际大小。

### Task 8: T8 — 贯通验收、文档和发布门

**Files:** 新增 `tests/ui/test_mechanical_three_views.py`；更新 README.md、docs 下实际用户指南与 ADR（仅必要决策）、`.omo/evidence/mechanical-three-views/acceptance.md`、ledger。

**Interfaces:** 完整用户流程与前述模块一致，不加临时演示专用路径。

- [ ] 写贯通测试：打开法兰→切工程图→第一角主俯左→标孔径→切3D修改孔径→更新→存档重开→撤销/重做→DXF/PDF 数值一致；第二例用不对称阶梯件区分左右/上下。
- [ ] 运行 `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_mechanical_three_views.py -q`，先见 RED，再修复真实接线缺口至 GREEN。
- [ ] 验证未提交草图跨页保留、右侧图形信息页/浮动设置、底部 CLI/未连接 AI/计划共用，以及 .my2d 原有自由绘图路径。
- [ ] 按设计样本矩阵验收：盲/沉孔、圆角、斜孔、重复孔、多实体遮挡、复杂曲线、空/非法模型；记录失败样本，不能用正方体截图代替。
- [ ] 完成改动路径四门后，最终集成只跑一次全量 `uv run ruff check .`、`uv run ruff format --check .`、`uv run basedpyright`、`QT_QPA_PLATFORM=offscreen uv run pytest -q`。区分基线既有问题和本功能回归；Windows 门由 CI 验证，不把本机通过等同跨平台通过。
- [ ] 写用户操作指南、首版限制和实际性能；记录 P0/P1 发布判断、手工验收与证据。只有关联、更新、存档、出图全部过门才标完整首版交付。

## 计划自查与交付口径

规格覆盖映射：对标流程→T4/T5；三 Tab→T4；数据/重放→T1/T2；HLR→T0/T3；标注/身份→T0/T6；线程/缓存→T0/T5；输出→T7；兼容和全程→T8。五项 Review Focus 均有指定测试。

本轮原为评估交付；用户已批准实施。T0 证据记录在 probe.md，任务完成情况以勾选和执行账本为准，未勾选的后续功能仍未交付。
