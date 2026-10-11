# MyCAD

Ubuntu 桌面端开源 CAD 建模软件，并内置智能体助手：以可编程几何与可确认的命令计划为核心，兼顾传统桌面建模交互。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/需求分析书.md](docs/需求分析书.md) | 产品定位、范围、功能/非功能需求、分期与验收 |
| [docs/技术路线.md](docs/技术路线.md) | 架构选型、命令总线、演进阶段与目录规划 |
| [docs/UI设计初稿.md](docs/UI设计初稿.md) | 主布局、菜单/工具栏、左右底栏与交互规格 |

上述文档为当前规格基线；实现前以它们为准。

## 技术栈摘要

- **几何内核**：OpenCascade（OCCT），经 build123d 暴露
- **桌面 UI**：PySide6（Qt6）——阶段 1，阶段 0 不含
- **智能体**：计划生成 → 用户确认 → 经统一 Command Bus 执行
- **目标平台**：Ubuntu 22.04+

详细说明见 [技术路线](docs/技术路线.md)。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源发布。  
发行物请保留 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)。

Apache-2.0 相对 MIT 增加了明确的专利授权与 NOTICE 保留义务，同时不采用 GPL/AGPL 式强 copyleft。

## 贡献

目前处于文档与规格阶段。提交代码或文档补丁前，请先阅读 `docs/` 下三份基线文档，并确保改动与其中约定一致。贡献默认按 Apache-2.0 授权（见 License 第 5 节）。

## 状态：阶段 0（headless 可编程内核）

阶段 0 交付一个**无 UI** 的可编程建模内核，以法兰件为验收牵引。已具备：

- **八条内置建模命令**：`box` / `cylinder` / `extrude` / `revolve` / `hole` /
  `hole-pattern` / `fillet` / `cut`（`mycad commands` 可列出）。
- **唯一写入路径**：所有模型修改经 Command Bus；undo 等于删除命令后全量重放
  （[ADR-001](docs/adr/ADR-001-command-bus-and-history-replay.md)）。
- **批事务**：`begin-batch` / `end-batch` 包裹的命令整体成功或整体回滚。
- **参数化重放**：改写历史命令的参数后重建几何，谓词选择器在新尺寸下仍解析到
  同一语义面组。
- **存档**：`.mc.json` v1 是纯 JSON 命令历史加审计六字段
  （[ADR-002](docs/adr/ADR-002-document-archive-format-v1.md)）。
- **导出**：STEP 与 STL（按扩展名解析 FormatProvider，
  [ADR-005](docs/adr/ADR-005-format-provider-tiers.md)）。
- **CLI**：REPL、ASCII 脚本、JSON 计划三种驱动方式，文本与 JSON 双向等价。
- **插件缝**：entry-points 发现 + manifest 主版本门控
  （[ADR-003](docs/adr/ADR-003-extension-points-and-plugin-api-versioning.md)）。

尚未开始：PySide6 外壳与 3D 预览（阶段 1）、智能体对话闭环（阶段 2）。

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

交互式使用直接运行 `uv run mycad`，输入 `help` 查看内建命令。

## 平台支持矩阵

| 层级 | 平台 | 阶段 0 状态 |
|------|------|------------|
| T1 | Ubuntu 22.04 / 24.04 x86-64、Windows | 支持；CI 三个 job 覆盖 |
| T2 | 信创 aarch64 | 预期可用（要求 glibc ≥ 2.31）；阶段 0 不进 CI |
| T3 | 龙芯 LoongArch | 评估中；go/no-go 定于阶段 1 末 |

分层依据与依赖策略见
[ADR-006](docs/adr/ADR-006-platform-tiering.md)。

## 开发环境

仓库使用 [uv](https://docs.astral.sh/uv/) 作为 Python 工具链。安装 uv 后：

```bash
# 解析并安装锁定的依赖（首次会构建 .venv/ 与 uv.lock）
uv sync

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
| MCP 边界与确认红线 | 阶段 2 落地，阶段 0 零依赖 | [ADR-004](docs/adr/ADR-004-mcp-boundary.md) |
| 格式提供方分层（商业格式墙） | 阶段 0 定界 | [ADR-005](docs/adr/ADR-005-format-provider-tiers.md) |

阶段 0 **不含**任何 MCP SDK、LLM 调用或网络代码。
