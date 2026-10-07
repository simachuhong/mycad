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

- **几何内核**：OpenCascade（OCCT），经 build123d / CadQuery 暴露
- **桌面 UI**：PySide6（Qt6）
- **智能体**：计划生成 → 用户确认 → 经统一 Command Bus 执行
- **目标平台**：Ubuntu 22.04+

详细说明见 [技术路线](docs/技术路线.md)。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源发布。  
发行物请保留 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)。

Apache-2.0 相对 MIT 增加了明确的专利授权与 NOTICE 保留义务，同时不采用 GPL/AGPL 式强 copyleft。

## 贡献

目前处于文档与规格阶段。提交代码或文档补丁前，请先阅读 `docs/` 下三份基线文档，并确保改动与其中约定一致。贡献默认按 Apache-2.0 授权（见 License 第 5 节）。

## 状态

仓库正处于基线文档落地阶段，应用程序代码尚未脚手架。

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
