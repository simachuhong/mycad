# ADR-006 平台分层

Status: Accepted 2026-09-17

## Context

MyCAD 的目标平台横跨主流桌面与信创（国产化）环境。OCCT Python 绑定（cadquery-ocp-novtk）的 wheel 覆盖矩阵是硬约束：manylinux_2_31_x86_64 / manylinux_2_31_aarch64 / win_amd64（cp310–314，E1）——Linux 直装的前提是 glibc≥2.31；龙芯 LoongArch64 无 PyPI 官方 wheel 通道（E9）。信创侧 glibc 精确矩阵（E2）显示：统信 UOS V20 桌面 D 版（Debian 10，glibc 2.28）确定不满足；银河麒麟 V10 SP1+（Debian 11，glibc 2.31 + 麒麟补丁）、统信 UOS Server 20（openEuler，约 2.31–2.34）、银河麒麟 V11（约 2.35+）可直装。平台承诺必须分层声明，避免"全平台支持"的过度承诺。

## Decision

1. **T1（一级支持）**：Ubuntu 22.04 / 24.04 x64 + Windows 10/11 x64。CI 三 job（ubuntu-22.04 / ubuntu-24.04 / windows-latest）全过，pip wheel 直装（OCP manylinux_2_31_x86_64 与 win_amd64 覆盖，E1/E11 尖刺实证）。
2. **T2（信创直装层）**：麒麟 V10 SP1+（glibc 2.31 + 麒麟补丁）/ UOS Server 20 / 麒麟 V11，运行于鲲鹏/飞腾 aarch64：OCP manylinux_2_31_aarch64 wheel 可用；阶段 1 已做 aarch64 QEMU 回归（880 测试通过/2 deselect，见证据目录）。2026-10-24 P2-25 将 PySide6、pyqtgraph、PyOpenGL 移出默认依赖：headless 安装不再解析 PySide6 wheel；该拆分后的干净 aarch64 安装尚未实测，故仍是预期组合，不构成原生平台支持声明。桌面额外依赖的当前 glibc 地板见第 3 条。（阶段 0/1 CI 不含 aarch64。）
3. **基线声明**：Linux 几何运行时依赖的 wheel 基线为 glibc≥2.31（manylinux_2_31，OCP 绑定轮地板）；它不是整套依赖在所有发行版都已安装验证的承诺。阶段 1 的 QEMU 实证发现 PySide6 6.12.0 aarch64 wheel 为 manylinux_2_39；Linux **桌面**形态因此要求 glibc≥2.39。P2-25 现将 `PySide6`、`pyqtgraph`、`PyOpenGL` 放在 `desktop` extra，默认 headless 闭包不再要求 PySide6。UOS V20 桌面 D 版（glibc 2.28）仍不满足几何运行时 wheel 基线（R13）；升级到麒麟 V11 / UOS E、容器分发或源构建是单独的部署路径。PySide6 x86_64 wheel 的 manylinux 基线随发行版本变化，T1 按已列 CI runner 验证，不从 aarch64 wheel 推断。
4. **x86 国产 CPU**：海光/兆芯 = x86_64，走 T1/T2 同栈（manylinux x86_64 wheel），无单独分层。
5. **T3（龙芯，go/no-go 已决：no-go）**：LoongArch64 技术可行——CPython 3.12 原生识别 loongarch64 triplet；但 PyPI 官方拒收其 wheel（discuss.python.org #105548，PEP 流程未落地），龙芯镜像 pypi.loongnix.cn（devpi，包索引在 `/loongson/pypi/+simple/<pkg>/`）实测：cadquery-ocp-novtk / cadquery-ocp / build123d 的 loongarch64 wheel 数为 **0**（官方 PyPI 全历史亦 0）；PySide6 的 loong 轮仅 Qt 6.2.0（cp37/cp38），numpy 的 loong 轮止步 1.8.2（cp36）——对本仓 Python 3.12 + pyside6==6.12.0 + cadquery-ocp-novtk==7.9.3.1.1 形态 headless 与 GUI 两半均不可直装，源构建 OCCT/OCP 评估为高成本长周期项。**2026-10-22 阶段 1 末 spike 决议 no-go**（证据 .omo/evidence/t3-loongson-spike-phase1-desktop-shell.md）：T3 降级为战略路线、阶段 2 不作工程承诺；复评触发器：(a) cadquery-ocp(-novtk) 出现 cp312 loongarch64 wheel；(b) PySide6 ≥6.8 出现 loongarch64 wheel；(c) LatX x86 翻译通道实证可跑本仓闭包（需硬件）。no-go 期间不购硬件、不进 CI、不对外承诺。
6. **申威（SW64）**：生态基本不可行，不纳入（E2）。

## 基线偏离

本 ADR 记录基线偏离 ①（打包主路径）。基线技术路线在「关键环境与依赖策略」（`docs/技术路线.md:92`）中将 conda-forge 设想为推荐开发环境主路径（"conda-forge 提供 OCCT 与相关绑定，降低系统库冲突"；需求分析书 NF-01 亦把依赖安装策略指向技术路线）。本决策将打包主路径改为 pip+uv（`uv sync` / wheel 直装），依据：

- E1 一手源：PyPI build123d 官方 README 原文 "pip recommended for most users"；cadquery-ocp-novtk wheel 五平台齐全（cp310–314），pip 路径三平台可用。
- E11 本机实证：uv + 国内镜像安装 build123d 0.11.1 + OCP 7.9.3.1.1 成功，法兰尖刺通过。
- conda-forge 的 build123d 滞后至 0.9.1（pin ocp 7.8），与仓库锁定的 0.11.1 不兼容；conda 仅保留为离线/企业网备选（README 离线附录），不作主路径。

此偏离只改变依赖获取渠道，不改变任何架构决策（几何内核、绑定版本、CI 三 job 形态均不受影响）。

## Consequences

- 正面：分层承诺可验证（T1 有 CI 硬门控）；glibc≥2.31 基线与 wheel 矩阵对齐，避免"装不上"的支持负担；龙芯的 go/no-go 判据与时点兑现（阶段 1 末 spike 已决 no-go）。
- 负面/边界：UOS V20 桌面 D 版用户被明确排除在直装支持外（文档需显著声明）；T2 在阶段 1 实机回归之前只有 wheel 可得性证据、无端到端验证；龙芯需自维护 OCCT/OCP 源构建，成本高（最坏降级为"战略路线"，R8）。
- CI 范围重申：阶段 0 CI 仅 T1 三 job（ubuntu-22.04 / ubuntu-24.04 / windows-latest）；aarch64 / QEMU / 龙芯 CI 任务不做（由本 ADR 记录，阶段 1 末 spike 评估）。
- P2-25 变更记录（2026-10-24）：`uv sync --no-dev` 安装 headless 默认闭包；`uv sync --no-dev --extra desktop` 增加桌面依赖。GitHub Actions 定义三平台质量 job（安装 `desktop` extra）和 Ubuntu 22.04 headless 完整 CLI/STEP/STL/archive 闭环。workflow 配置本身不代表当前未提交工作树已有远端 CI 结果。

## References

- docs/需求分析书.md NF-01（平台与依赖安装策略）
- docs/技术路线.md §4「关键环境与依赖策略」（conda-forge 主路径设想——本 ADR 偏离 ① 的基线对象）
- 研究台账 A18（平台分层）、A2（pip+uv 主路径）、E1（wheel 矩阵与官方 README）、E2（信创 glibc 精确矩阵）、E9（龙芯生态）、E11（本机安装实证）、R8（龙芯 go/no-go）、R13（manylinux_2_31 基线与 UOS V20 已知不支持）
- .omo/plans/phase0-mvp.md C1/C9（CI 三 job 与跨平台纪律）、T4（本 ADR 指令与偏离 ① 记录要求）
- [PyPI cadquery-ocp-novtk 7.9.3.1.1](https://pypi.org/project/cadquery-ocp-novtk/7.9.3.1.1/)；[PyPI PySide6 6.12.0](https://pypi.org/project/PySide6/6.12.0/)（wheel compatibility tags）
