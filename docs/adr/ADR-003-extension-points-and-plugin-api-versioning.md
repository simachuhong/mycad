# ADR-003 扩展点与插件 API 版本

Status: Accepted 2026-09-17

## Context

MyCAD 的可扩展性需要标准机制：第三方（以及未来的官方可选件）以插件形式贡献命令与格式，而不修改核心。Python 当前的标准机制是 importlib.metadata entry points（FreeCAD Workbench、Blender addon 等生态验证过的模式，A13）。核心问题有四个：插件如何被发现与描述、API 兼容性如何判定、headless 核心如何不依赖 Qt、插件命令如何进入唯一写入路径（ADR-001）而不破坏重放语义。信任模型需要一条诚实声明：任意 Python 插件即任意代码执行（R9），阶段 0 不做插件沙箱化——沙箱（NF-07）约束的是未来 Agent 生成的代码，不是人类安装的插件。

## Decision

1. **entry-point 组**：`mycad.commands`（命令贡献）与 `mycad.formats`（格式提供方贡献）两个组先落地；`mycad.datum`（基准/坐标系扩展）与 `mycad.inspect`（检查器/查询扩展）仅在文字上预留组名，阶段 0 不定义行为。
2. **manifest 契约**：每个插件模块暴露固定名 `manifest`，承载 id / version / api_version / permissions / homepage 五字段。核心以 `CURRENT_API_VERSION="1.0"` 判定兼容：插件 api_version 主版本为 1 视为兼容，其他主版本一律跳过。
3. **manifest 定位算法（#round7-4）**：不设第三个 entry 组——核心导入每个贡献 entry 的 `EntryPoint.module`，在模块属性中寻找固定名 `manifest`。接受三种形态：零参 callable 的返回值、dict、PluginManifest 数据类实例；按 module memoize，每个模块只取一次。字段损坏（类型/结构不合法）报 manifest-error；属性缺失报 missing-manifest；api_version 主版本不符报 incompatible-api。
4. **多 entry 合并**：同一插件向多个组贡献 entry 时，合并为一个 DiscoveredPlugin，以 `entrypoint: tuple[str, ...]` 记录去重排序后的 `<group>:<module>:<attr>` 引用串。
5. **不兼容即跳过**：api_version 主版本不兼容的插件被跳过并输出 warning，核心启动与其余插件不受影响。
6. **信任模型**：插件 = 全信任 Python（R9）：manifest 的 permissions 字段是声明性告知，不做沙箱化隔离；沙箱只约束未来 Agent 生成的代码（NF-07），不适用于人类安装的插件。安装第三方插件即信任其作者。
7. **headless 信号**：核心提供五个信号——pre_command、post_command、command_amended、document_saving、document_saved——供插件观察文档生命周期；不提供改模型的旁路（改模型只能经 Command Bus，ADR-001）。
8. **插件命令贡献契约（写死）**：`mycad.commands` 组 entry 的 callable 返回 `list[CommandContribution]`。`CommandContribution(spec: CommandSpec, handler_factory: Callable[[], CommandHandler] | None)` 是唯一携带形式（不拆第二个 entry 组）：spec 承载命令定义及其版本；handler_factory 省略时核心以 BuiltinModelingHandler 兜底（适用声明式建模命令）。插件处理器须实现核心的 CommandHandler Protocol——实例属性 `command_id` 加 `handle(params, ctx)` 方法，工厂零参并返回已绑定自身 id 的实例；装配时按 `(spec.id, spec.version)` 独立绑定，处理上下文携带该版本，同一命令 ID 的版本不可相互覆盖。新交互执行默认选最新版本；计划与历史按显式版本解析 schema 和 handler，打开、undo、redo、编辑及失败恢复必须重放历史记录的精确版本。经 api_version 主版本门控通过后才实例化。demo.ping 型非几何命令必须自带 handler（没有可兜底的建模语义）。

   命令 handler 会在打开、undo、redo、编辑和失败恢复时重放，必须确定且可重放；其状态变更只能经 `ctx.kernel.apply` 表达。Bus 的回滚只恢复文档状态与几何，不能撤销文件写入、网络请求、通知等外部副作用。带外部副作用的 handler 违反此契约，其副作用不受回滚保证。
9. **命令 id 命名空间与 P2 G 首批释放**：阶段 0 只注册 8 条 P0 命令。P2-32 释放内置 `sketch.create@1`：参数为稳定 `sketch_id`、右手 work-plane frame 与带稳定 `entity_id` 的 line/polyline/circle/arc/rectangle 初始实体数组；构造几何使用同一几何类型并标记 `construction=true`。后续 `sketch.create@2` 在新 schema 中要求图层表和每个图元的图层名，并可附加基于既有选择器的平面 `support_face` 锚点；@1 的 schema 与重放保持不变。`sketch.create@3` 可携带长度、点距、角度、半径、直径尺寸标注及已由初始直线几何精确满足的推断水平/竖直关系；尺寸值须与几何一致，标注样式保存精度与显示比例。旧版本 schema 与重放保持不变。命令完整 schema 与存档门槛见 ADR-009。P2-33 释放 `sketch.constraint.add@1`，为一个稳定 constraint ID、已释放图元的稳定引用、明确类型和驱动/参考语义；`sketch.constraint.add@2` 仅为尺寸记录增加可选 `precision`（0–8）和 `scale`（0.1–100）。约束结构、求解与重放契约见 ADR-010。

   P2-36 释放 `feature.extrude@2`、`feature.revolve@2` 和 `feature.hole@2`：拉伸与旋转支持 `{type:"sketch", sketch_id}` 轮廓引用；孔支持引用一张由非构造圆组成的草图，并要求目标为共面的平面实体面。新版也保留对应 v1 参数格式；`feature.extrude@1`、`feature.revolve@1` 和 `feature.hole@1` 的 schema、语义和旧档案重放不变。草图轮廓按引用草图在命令重放点的状态重新生成结果。

   P2-36 后续补充释放 `feature.extrude@3`：在 @2 的参数上追加可选 `extent_mode`，枚举 `one_sided` / `symmetric`，默认 `one_sided`。`symmetric` 将正 `distance` 视为总深度，在草图平面或 XY 参数截面两侧均分；对称深度必须为正数。面拉伸保留单侧有符号距离语义并明确拒绝 `symmetric`。@1/@2 的 schema、几何语义和存档重放保持不变，@3 接受 @2 的既有 profile 形状。P2-32 后续 `sketch.create@2` 支持选择平面面并按几何锚点重放；曲面面、失效锚点恢复和上游模型变化后的完整下游草图更新仍不支持。

   P2-36 再补充释放 `feature.extrude@4`：旧单侧/对称参数形状继续有效，并为草图轮廓增加无距离值的 `extent_mode="to_face"` 分支及稳定平面面定位器 `target_face`。几何适配复用 build123d `Until.NEXT`，以选中的有限目标面作为终止对象；目标面必须覆盖截面到达终止位置的区域，非平面面与未能相交的选择明确失败。该分支只用于草图拉伸；@1–@3 与 @4 的单侧/对称及模型面拉伸语义保持不变。

   P2-36 再补充释放 `feature.revolve@3`：在 @2 轮廓、角度和布尔方式上，保留全局轴参数，并新增互斥的 `axis_reference: {type:"sketch_line", sketch_id, entity_id}` 分支；该分支只接受草图轮廓。引用必须解析到历史中的 `LineEntity(construction=true)`，并按草图工作平面转换到模型坐标后作为回转轴。全局 `axis` 与 `axis_reference` 不得同时出现；@1/@2 schema、语义和存档重放不变。UI 为已选轮廓草图列出构造直线，预览成功后才可确认。此操作对应 Solid Edge Ordered Revolve 以草图中心线指定旋转轴的工作流；模型棱边、圆柱面轴与跨草图轴选择仍未覆盖。

   P2-37 释放内置 `modify.chamfer@1`：参数为非空 `edges` 稳定/交互边选择器数组与正的 `distance`；所有选边使用相同距离，在公共边两侧形成等距倒角。affected_object 新增唯一值 `chamfer_edge`，UI 选择当前边并预览后显式确认，命令仍经 Bus 进入可重放历史。该首批流程对应 Solid Edge Chamfer 的选边与 setback 距离；角度/双 setback 和面基准模式尚未释放。

   P2-37 再释放内置 `modify.boolean_intersect@1`：参数为已有 `Tool` 定义中的一个内联盒或圆柱。该命令将当前聚合模型与该工具体求交，只保留非空公共实体；空交集视为失败，不写入命令历史。工具体由命令参数确定并在操作后消耗。affected_object 新增唯一值 `intersection_tool_body`。UI 沿用工具体放置、候选预览与显式确认路径，CLI/存档/undo/redo 使用同一可重放参数。此范围对照 Siemens Solid Edge BooleanFeatures API 的实体交集操作，但不表示支持实体间选择。

   P2-37 后续释放 `modify.boolean_bodies@1`、`modify.body_transform@1` 与 `modify.body_pattern@1`（均要求 archive v2）：实体选择参数使用体积、质心、包围框及必要的重复签名 rank，运行时 `BodyId` 不落盘；重放若选择失效则明确失败，不静默换体。实体布尔按 UI 选择顺序指定目标体/刀具体，支持并集、差集、交集及明确的保留/消耗刀具体选项；空结果失败且不写历史，多个有效结果实体都保留。实体变换支持沿量值移动、围绕给定轴/中心旋转、关于给定平面镜像替换，以及位移复制并保留原体。实体阵列支持 2–64 个实例的直线阵列和环形阵列；数量包含种子，360° 环阵均匀分布且不重复末端。所有流程通过实际视口实体选择填入几何定位器，再经隔离预览、显式确认和 Bus 历史重放；本切片不实现装配关系、面/片体布尔、特征阵列依赖关系或跨文档实体身份。

   `chamfer` alias 不再保留；shell/draft/sweep 与 datum.* 等其它命令仍保留给后续核心版本。`modify.boolean_intersect` 已释放的 ID 只具备上述内联工具体语义；`modify.boolean_bodies` 提供所述双实体首版，并集/差集/交集均不隐式替换到另一个候选体。`modify.body_transform` 与 `modify.body_pattern` 只修改/复制独立实体，不表示装配求解或关联特征阵列。P2-34 编辑与 P2-35 图层/标注仍按任务分别审批命令及版本，不得提前占用。插件命令 id 与内置或彼此冲突时按命令冲突错误语义处理：跳过该插件条目并 warning，核心不崩。

## Consequences

- 正面：发现机制零配置（包元数据即注册表）；API 主版本门控使核心与插件可独立演进；契约单一（CommandContribution 一种携带形式）避免双通道漂移。
- 负面：插件即任意代码，恶意插件的防护责任在安装者（文档明示信任模型）；manifest 三形态接受换来零依赖的渐进兼容；插件命令一旦入史，其 handler 必须永久可重放（否则破坏 ADR-001 的重放不变量）——api_version 门控在实例化前执行，降低不兼容代码被执行的面。
- 阶段 0 落地范围：entry 组与 manifest 定位算法、五个信号、贡献契约为已实现缝；`mycad.datum`/`mycad.inspect` 组与插件分发/安装工具为后续演进。

## References

- docs/需求分析书.md NF-06（可扩展 UI 三注册函数：后端命令/格式缝阶段 0 落地，UI 注册在阶段 1）、NF-07（Agent 生成代码沙箱）
- docs/技术路线.md §2 原则 5（UI 可注册扩展）
- 研究台账 A13（entry points + manifest 契约）、R9（插件全信任、沙箱只约束 Agent 生成代码）
- .omo/plans/phase0-mvp.md T4（#round7-4 manifest 定位算法、贡献契约写死）、T7/T9/T10（发现、装配与装载实现）
- ADR-001（唯一写入路径与重放不变量）、ADR-005（mycad.formats 组的 FormatProvider 契约）
