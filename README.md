# MyCAD

Ubuntu 桌面端开源 CAD 建模软件：以可编程几何、可确认的命令计划和传统桌面建模交互为核心。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/需求分析书.md](docs/需求分析书.md) | 产品定位、范围、功能/非功能需求、分期与验收 |
| [docs/技术路线.md](docs/技术路线.md) | 架构选型、命令总线、演进阶段与目录规划 |
| [docs/UI设计初稿.md](docs/UI设计初稿.md) | 主布局、菜单/工具栏、左右底栏与交互规格 |
| [Phase 2 Todo](.omo/plans/phase2-agent-loop.md) | 基础 CAD：G 范围工程实现已有证据；二维人工验收退回，交互整改及复验状态见交接记录 |
| [docs/phase2-UI设计方案.md](docs/phase2-UI设计方案.md) | 阶段 2 基础工作台规格；明亮视觉方向已获积极反馈，操作与实现待验收 |
| [Phase 3 Todo](.omo/plans/phase3-extensions.md) | AI、企业接口与数据库扩展；默认 MySQL、达梦（待实施） |
| [docs/phase3-扩展设计方案.md](docs/phase3-扩展设计方案.md) | AI provider/models、PLM/CAPP/Git/编码预留与双库连接配置规格 |

前三份文档为当前规格基线；Phase 2/3 计划与设计方案记录后续范围，不代表相关功能已实现。原 v0.1 原型含跨阶段画面，交付范围以拆分后的计划为准。

## 技术栈摘要

- **几何内核**：OpenCascade（OCCT），经 build123d 暴露
- **桌面 UI**：PySide6（Qt6）——阶段 1 五区外壳已交付；Qt/GL 依赖属于可选 `desktop` extra
- **计划执行**：结构化计划经用户确认后由统一 Command Bus 执行；LLM 计划生成属于 Phase 3
- **目标平台**：Ubuntu 22.04+

详细说明见 [技术路线](docs/技术路线.md)。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源发布。
发行物请保留 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)。

Apache-2.0 相对 MIT 增加了明确的专利授权与 NOTICE 保留义务，同时不采用 GPL/AGPL 式强 copyleft。

## 贡献

提交代码或文档补丁前，请先阅读 `docs/` 下三份基线文档，并确保改动与其中约定一致。贡献默认按 Apache-2.0 授权（见 License 第 5 节）。

## 状态：阶段 2 基础 CAD

P2 G（P2-32～P2-37）已有工程实现与自检证据；**二维人工验收已开始，已两轮退回；图形工具、常驻草稿图层与图内标注工具、无损视图切换、右键结束与原点/栅格捕捉已整改，尚未通过用户复验**。当前结果、验证证据和走查顺序见 [P2 G 交接](.omo/evidence/task-P2-G-manual-handoff.md) 与 [条款映射](.omo/evidence/task-P2-G-final-traceability.md)。阶段 2 其余范围和发布验收以 [Phase 2 Todo](.omo/plans/phase2-agent-loop.md) 为准；阶段 3 AI、企业接口与 MySQL/达梦尚未实施。

建模交互使用 [Solid Edge 操作验收基线](docs/design/solid-edge-interaction-acceptance.md)。已有平面推拉使用所选面的完整边界并保留孔洞；正距离外拉、负距离内推。新建参数圆/矩形需显式选择“XY 截面”。当前平面推拉属于扫掠与布尔增减，不等同于完整同步面编辑。

### 当前可用流程

- **新建文档**：统一“新建”入口选择二维图或三维零件；装配体显示为规划中并禁用。取消选择不改变当前文档。
- **工作区布局**：二维仅保留右侧“二维功能”面板，绘图、UCS、修改、图形共用 Tab；面板可左右停靠、浮动、缩放与关闭，从“工具栏与面板”恢复。图形页按草图列出图元、约束与驱动/参考尺寸，与画布选择联动，双击尺寸继续在图中编辑。坐标输入和连线按钮移入绘图页，完成/取消草图位于顶部工具栏。底部共享“信息 / CLI / AI 对话 / 计划”容器，二维默认显示收起的标签栏，点击展开、再点当前标签或“收起”折叠；当前提示保留在状态栏，完整提示进入信息页。CLI 和输入草稿在二维/三维切换间保留；未提交草图时先完成或取消草稿再执行 CLI 写入命令。AI 窗口已提供，但尚未连接服务，发送按钮禁用，不会生成或发送消息。三维启动仍默认隐藏底部面板，可从“视图 / 智能体”打开。工具栏与右侧面板共同记忆布局；“视图 → 重置工作台布局”恢复默认。
- **二维绘图与草稿编辑**：独立 `drawing2d` 文档，在主窗口内嵌工作区绘制，绘图/修改/尺寸标注三个可独立停靠、悬浮的原生工具栏与 UCS 原点/方向；直线连续接段，Enter/右键/Esc结束、C或首点捕捉闭合。完成后保留同平面已提交图形作为只读捕捉参照。XY/XZ/YZ 或选面工作平面；线、折线、圆、顺逆圆弧、矩形、控制点式三次 B 样条和构造几何；精确局部坐标输入、正交、UCS原点/独立栅格捕捉、端点/交点/中点/圆心/切点/垂足捕捉。选择工具支持空白处拖拽或两次单击框选：从左到右蓝色实线框仅选完全包含的图元，从右到左绿色虚线框选包含或与框线相交的图元；Ctrl 加选、Shift 减选、Esc/右键取消。独立二维图的已提交图元在存盘重开后仍可点选、框选和高亮；隐藏图层与三维草图只读参照不参与选择。框选可用于草稿移动/复制命令的对象选择阶段；包含已提交图元时保持选择并提示通过历史编辑修改，避免只修改混选中的部分草稿。未提交草稿可移动、复制、旋转、镜像、阵列、偏移、限定修剪/延伸/分割，并完整撤销/重做。移动/复制支持选择—基点—鼠标预览—落点，也可按住基点拖放；右侧参数面板“修改”页保留按 ΔU/ΔV 执行。旋转支持选择—中心—鼠标方向或键入角度（Enter 确认），可勾选参考旋转按中心—起点—目标三点操作；镜像用任意两点定义轴，默认保留原对象，可取消“镜像保留原对象”以替换。两者均支持预览、Esc 取消、撤销/重做，右侧“修改”页保留明确的数值执行按钮。正多边形支持 3–128 边、内接圆/外切圆模式，按中心—顶点或边中点绘制，保存为闭合多段线。二维点阵网格可用“网格 F7”复选框或 F7 显隐，隐藏不影响栅格捕捉；三维 XY 工作网格也使用点阵。直线连续修剪保留剩余线段的连通性。样条至少四个控制点，Enter/右键完成，支持控制点拖动、保存重放、原生 DXF SPLINE 输出和闭合轮廓建模；尚不支持拟合点/周期/有理样条、样条修剪/延伸/偏移。闭合路径/矩形按两个唯一交点修剪或拆成两条开放路径；复杂、退化或歧义结果明确拒绝。
- **图内尺寸标注**：智能、水平、垂直、对齐、角度、半径、直径、弧长、连续、基线、坐标共 11 个独立工具；在图中拾取端点/圆心/顶点/线段、随鼠标预览并点击放置，支持中键平移和滚轮缩放。新尺寸默认驱动，可关闭“驱动尺寸”切换为仅测量的参考尺寸；在尺寸旁输入数值、预览并显式确认；双击尺寸使用画布内数值框，拖动文字或尺寸线调整位置，Esc 取消。草稿和同平面已提交图形共用操作；新尺寸默认存入自动创建的 DIM 层，可在工具栏选择其他标注层或使用当前层；独立标注层不随引用几何隐藏。线性尺寸提供自动、固定起点、固定终点、中心对称；自动优先遵守已有固定/锁定关系，否则保持首点或圆心。固定方式为临时编辑定位，不增加永久固定约束；显示真实自由度并在画布标红冲突图形。标注位置、图层、投影方向、固定方式、小数位和比例随档案保存、撤销与重放。
- **参数化草图**：受限 PlaneGCS 关系和长度/距离/角度/半径/直径/弧长，驱动与参考尺寸分开；显示自由度、冲突关系和图元位置，失败不能确认，分支变化需额外核对。已提交草图的数值尺寸可以修改，预览同时重建下游实体；确认后追加审计历史，撤销/重做和重开使用冻结解。锁定图层不能被直接或间接求解移动，参考测量仍可用。
- **图层与 DXF**：非模态图层表统一控制整张图纸的草稿和已提交对象，提供颜色、线型、线宽及独立的显示/隐藏、冻结/解冻、锁定/解锁。冻结层不参与显示再生、适配范围、捕捉和选择；关闭层仍计入适配范围；解冻保持原显隐状态，当前绘图层不能冻结。隐藏/冻结不解除驱动约束，旧尺寸可批量迁入 DIM；图层状态支持撤销、保存和 DXF 往返，以及线性、投影、角度、径向、弧长和坐标尺寸。DXF R2010 指定子集先显示实际输出字节的缩放/平移预览，再确认原子写入。未知单位要求输入；不支持的实体、带 bulge 圆弧或宽度的 LWPOLYLINE、外部无关联尺寸等通过报告披露，不能误报完整交换。
- **草图驱动三维**：拉伸、旋转、孔和孔阵列，支持已公布的新建/合并/切除、正负方向、对称深度、到平面和盲深/贯穿模式。法兰、阶梯轴、长圆孔安装板有从空白 GUI 创建、修改、undo/redo、重开与 STEP 的自动流程证据。
- **多实体修改**：多边圆角/倒角，目标体与刀具体并/差/交及保留/消耗，移动/旋转/复制/镜像，通用线性/完整或部分环形阵列。实体树显示来源步骤、结果序号、输入关系，可打开历史预览；逐体显隐仅影响显示和拾取。对称支架和通用阵列改参有完整任务级证据。
- **视口交互**：固定逻辑像素 XYZ 方向标及原点标记，参数条位于视口外；中键旋转、Shift+中键平移、滚轮缩放。数值输入/方向手柄接受后，只有对应当前文档修订的最新有效预览能够提交；撤销、重做和其他写入使旧预览失效。

- **机械三视图与工程图**：中央常驻平面草图、工程图、3D 三页；A4/A3、第一/第三角投影、图中直接放置/对齐/比例手柄、关联参考标注、模型更新状态与失关联提示、已完成草图直接作为平面视图入纸（无需实体）、v3 随 `.my2d`/`.my3d` 存档、DXF/PDF 出图。草图尺寸驱动规则保持独立。首次投影有进程准备时间；首版采用保守来源关联，复杂拓扑修改需重新关联。见 [工程图操作指南](docs/工程图操作指南.md) 与 [验收记录](.omo/evidence/mechanical-three-views/acceptance.md)。

### 支持边界

直接画布几何编辑按用户选择仅限**未提交草稿**；已提交尺寸修订可用。完整 IntelliSketch、通用约束引用迁移、复杂偏移自动拓扑修复、闭合路径跨段拖动修剪、装配配合和完整同步建模不在本次能力声明内。实体来源是操作输入关系，不能当作逐面拓扑持久 lineage。失效或歧义几何选择器明确拒绝。

DXF/STEP 的目标 AutoCAD/Solid Edge 实机显示、字体、设备交互和平台表现仍由用户验收；自动测试与 XCB 自检截图不代表 Solid Edge 等价或人工验收通过。PlaneGCS 在 T2/aarch64 的构建未验证；缺少求解器时普通绘图仍可用，并明确提示求解不可用。

### 架构与既有能力

阶段 0 可编程内核和阶段 1 五区桌面外壳已交付；P2 F 三维工作台工程收口见 [F 记录](.omo/evidence/task-P2-F-closure.md)。

- **唯一写入路径**：Command Bus；undo 为删除命令后全量重放，批事务整体成功或回滚（[ADR-001](docs/adr/ADR-001-command-bus-and-history-replay.md)）。
- **版本化存档**：桌面保存默认采用二维图 `.my2d`、三维零件 `.my3d`，省略后缀时自动补全；`.masm` 预留给尚未实现的装配文档。保存成功后状态栏显示完整路径，标题显示文件名，并记住最近的存档目录。打开窗口兼容旧 `.mc.json`，也可切换“所有文件”找回此前无后缀的存档。文件内容仍为纯 JSON 命令历史、审计六字段；CLI 的 `open` / `save` 和计划的 `outputs.archive` 也接受新后缀，原有批处理默认文件名保持兼容。旧 `.mc.json` v1 可读，草图和独立二维图使用版本化 schema。历史修改保留原时间戳和修订记录（[ADR-002](docs/adr/ADR-002-document-archive-format-v1.md)）。
- **命令、格式和插件**：命令按 ID/版本绑定；CLI REPL、ASCII/JSON 计划、STEP/STL/DXF 格式提供方、entry-point 插件。`mycad commands` 列出实际已注册命令（[ADR-003](docs/adr/ADR-003-extension-points-and-plugin-api-versioning.md)、[ADR-005](docs/adr/ADR-005-format-provider-tiers.md)）。
- **桌面外壳**：文件生命周期、GL 视口、底栏 CLI、拾取/结构树双向高亮、计划卡片六态确认。所有模型写入均需用户显式确认。

## 快速开始：三条命令跑通法兰

```bash
uv sync
uv run mycad run examples/flange_script.txt
uv run mycad run --json examples/flange_plan.json
```

两条路径描述同一个零件（OD80 × 8、中心孔 φ20、4 × φ6 均布于 PCD50），
产出 `flange.step` / `flange.stl` / `flange.mc.json`（计划路径的产物位于
`examples/` 下，以计划文件名为基名）。体积真值为
`math.pi*8*(40**2-10**2-4*3**2)` ≈ 36794.333 mm³，由
`tests/test_acceptance_flange.py` 断言。

交互式使用直接运行 `uv run mycad`，输入 `help` 查看内建命令。默认安装保留 headless CLI。
需要桌面与草图求解时先运行 `uv sync --extra desktop --extra sketch-constraints`，再执行 `uv run mycad gui` 打开五区主窗；
无显示环境（CI/远程桌面/SSH）可设置 `QT_QPA_PLATFORM=offscreen`，但离屏测试不替代真实 GL 验收。

## 平台支持矩阵

| 层级 | 平台 | headless | 桌面 |
|------|------|----------|------|
| T1 | Ubuntu 22.04 / 24.04 x86-64、Windows x86-64 | 支持范围；CI 定义了三平台质量 job 和 Ubuntu 22.04 干净安装闭环 | 支持范围；安装 `desktop` extra，质量 job 装此 extra；实际状态以当前提交 CI 和桌面证据为准 |
| T2 | 信创 aarch64 | OCP manylinux wheel 基线为 glibc ≥ 2.31；本次依赖拆分后的干净原生安装未验证，不作实机支持声明 | 当前 PySide6 aarch64 wheel 要求 glibc ≥ 2.39；未验证为支持平台 |
| T3 | 龙芯 LoongArch | no-go | no-go |

分层依据与依赖策略见
[ADR-006](docs/adr/ADR-006-platform-tiering.md)。

## 开发环境

仓库使用 [uv](https://docs.astral.sh/uv/) 作为 Python 工具链。安装 uv 后：

```bash
# 开发环境包含测试工具、桌面和可选草图求解器
uv sync --extra desktop --extra sketch-constraints

# 在项目虚拟环境中执行命令
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run pytest -q
```

CI 工作流定义于 `.github/workflows/ci.yml`，覆盖 `ubuntu-22.04`、
`ubuntu-24.04` 与 `windows-latest` 三个 runner。

### 国内镜像

若直连 PyPI 受限，可通过环境变量切到国内镜像：

```bash
# 清华源
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
uv sync

# 或阿里源
export UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple
uv sync
```

仅安装 headless 运行依赖时使用 `uv sync --no-dev`；如需 GUI 运行依赖，使用
`uv sync --no-dev --extra desktop --extra sketch-constraints`。阶段 2 拆分与 wheel/glibc 边界见
[ADR-006](docs/adr/ADR-006-platform-tiering.md)。

也可以在 `~/.config/uv/uv.toml` 中固化该配置，避免每次临时设置。

> **注意**：切换索引后 `uv sync` 会把 `uv.lock` 中全部包的 `source` 与下载 URL 改写
> 为该镜像（hash 不变，完整性不受影响）。**不要提交这份改写**——CI 以 `--frozen` 安装，
> 一旦合入会把三个 runner 全部钉到该镜像。同步完成后执行 `git checkout uv.lock` 还原。

### 离线 / 无外网应急（conda / wheelhouse）

仅在完全无外网的环境下使用。conda-forge 上的 `build123d` 滞后于上游 0.9.1，
与本仓库锁定的 0.11.1 不兼容；wheelhouse 离线方案需要先用联网环境
`uv pip download` 把依赖下载到内网仓库。`pyproject.toml` 中锁定版本不可降级，
因此离线方案仅作为应急，不能替代正常的 `uv sync`。

## 插件与安全

- 插件经 Python entry-points 在**同一进程**内加载，等同完全信任其作者：
  没有沙箱、签名校验或权限强制（ADR-003）。
- manifest 的 `permissions` 字段在阶段 0 仅作声明展示，不做任何强制。
- 安装任何第三方插件前，请先审阅其源码。
- 最小示例插件见 [`plugins_examples/mycad_plugin_demo/`](plugins_examples/mycad_plugin_demo/)。
- 已加载与被跳过的插件可用 `uv run mycad plugins` 查看。

## 路标

| 方向 | 阶段 | 决策记录 |
|------|------|---------|
| 插件 API 版本化与扩展点 | 阶段 0 已埋缝 | [ADR-003](docs/adr/ADR-003-extension-points-and-plugin-api-versioning.md) |
| MCP 边界与确认红线 | 新计划迁至阶段 3；原 ADR 的阶段文字待实施前修订，阶段 0 零依赖 | [ADR-004](docs/adr/ADR-004-mcp-boundary.md) |
| 格式提供方分层（商业格式墙） | 阶段 0 定界 | [ADR-005](docs/adr/ADR-005-format-provider-tiers.md) |

阶段 0 **不含**任何 MCP SDK、LLM 调用或网络代码。
