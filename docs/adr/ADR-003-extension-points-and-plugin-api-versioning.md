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
8. **插件命令贡献契约（写死）**：`mycad.commands` 组 entry 的 callable 返回 `list[CommandContribution]`。`CommandContribution(spec: CommandSpec, handler_factory: Callable[[], CommandHandler] | None)` 是唯一携带形式（不拆第二个 entry 组）：spec 承载命令定义；handler_factory 省略时核心以 BuiltinModelingHandler 兜底（适用声明式建模命令）。插件处理器须实现核心的 CommandHandler Protocol——实例属性 `command_id` 加 `handle(params, ctx)` 方法，工厂零参并返回已绑定自身 id 的实例；经 api_version 主版本门控通过后才实例化。demo.ping 型非几何命令必须自带 handler（没有可兜底的建模语义）。
9. **命令 id 命名空间保留**：阶段 0 只注册 8 条 P0 命令；后续阶段的命令 id（chamfer/shell/union/intersect/pattern_linear/mirror/draft/sweep 与 datum.* 等）不提前占用，命名空间保留给未来核心版本与插件。插件命令 id 与内置或彼此冲突时按命令冲突错误语义处理：跳过该插件条目并 warning，核心不崩。

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
