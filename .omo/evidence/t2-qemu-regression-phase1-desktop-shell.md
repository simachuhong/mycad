# T2 aarch64 QEMU regression — conclusions (todo 15, ADR-006 §2)

**结论行: T2 条件通过** — headless 与非 GL UI 全部通过（880 passed / 2 deselected / exit 0），
3 项 emu/发行版限制记入问题清单，不阻塞阶段 1 交付，须在 F4 报告复述。

## 运行环境

- 主机: x86_64 Linux; docker 29.8.2 (host engine), binfmt qemu-aarch64 handler
  registered via `tonistiigi/binfmt:latest --install arm64` (docker.m.daocloud.io mirror —
  registry-1.docker.io unreachable from this network).
- 容器镜像: `mycad-t2-arm64:latest` built by `scripts/t2/Dockerfile`
  (base `docker.m.daocloud.io/library/ubuntu:24.04`; glibc 2.39-0ubuntu8.9; Python 3.12.3;
  libgl1/libegl1/libxkbcommon0/libglib2.0-0/libfreetype6/libfontconfig1/libdbus-1-3/
  libgl1-mesa-dri/libegl-mesa0/python3-pip/python3.12-venv/git).
- 路线: qemu-user 容器（非 qemu-system 云镜像）。理由: 无整机启动、镜像可钉死、
  被测对象（uv 解析 / wheel 安装 / pytest / Qt offscreen）均为进程级工作负载。
- 路线选择记录在 `scripts/t2_qemu_regression.sh` 头注 + 本文件；默认镜像可经 T2_IMAGE 覆盖
  （Debian bookworm glibc 2.36 为已存的失败探针）。

## 发现 1 — PySide6 6.12.0 aarch64 轮的 glibc 门槛（重要）

`uv sync --frozen` 在 glibc 2.36 (Debian bookworm) **失败**:
`pyside6==6.12.0` 只有 `manylinux_2_39_aarch64`（hint 原文于运行日志）。
在 glibc 2.39 (ubuntu:24.04) 成功: `Installed 70 packages in 2.00s`，
PySide6/build123d/cadquery-ocp-novtk 的 manylinux aarch64 wheel 均可得并 import 通过。
**影响**: ADR-006 的 T2 基线声明 glibc ≥ 2.31 对桌面壳依赖不再成立——
麒麟 V10 SP1 / UOS Server 20 等老基线发行版上 `uv sync` 会整体失败（即使只用 headless）。
**建议**（todo 16 ADR-006 更新时采纳）: T2 基线抬升至 glibc ≥ 2.39，或给 PySide6 加
`platform_machine == 'aarch64'` 条件包（老基线可装 headless 但无 GUI）。

## 发现 2 — NF-04 回放性能门在 emu 下不可测

`test_open_replay_performance_gate`: slowest replay 1759.9ms（门 <1000ms）；
同组回放 1315-1760ms 全部超标。x86_64 主机同测试长期通过。
属 qemu-user 指令翻译开销，非产品回归；**deselect 记录，需 T2 原生硬件复核**。

## 发现 3 — qemu-user 下离屏 GL 上下文创建失败

`tests/ui/test_shell_smoke.py::test_offscreen_gl_context_creation`:
`QOpenGLContext.create()` 恒 False（已装 mesa dri + LIBGL_ALWAYS_SOFTWARE=1 仍不行）
→ deselect。其余 68 个 tests/ui 测试在 emu 下全部通过（widget/lifecycle/picking/plan-cards）。
GL 视口渲染路径需 T2 原生硬件（或 qemu-system+GPU 直通）验证。

## 发现 4 — aarch64 运行时闭包多出 py-lib3mf（已在本次修掉）

`tests/test_notice.py::test_every_runtime_distribution_is_listed` 在 aarch64 失败:
NOTICE 未归属 `py-lib3mf`（uv.lock 对 aarch64 的平台条件依赖）。已修复:
NOTICE 增加 py-lib3mf 行（LGPL-3.0-or-later, 注明 aarch64-only）；x86_64 主机
test_notice.py 复跑 6 passed（该测试闭包⊆NOTICE 单向断言，添条目安全）。

## 发现 5 — Emu 环境修复（非产品）

- 容器缺 git（scope-audit 基线测试 shell out）→ prep 镜像加 git;
- bind-mount 仓库归属宿主 UID → 容器内 `git config --global --add safe.directory /work`;
- Debian/Ubuntu 把 ensurepip 拆进 python3.12-venv 包 → prep 镜像加该包（影响
  tests/plugins/test_demo_installed.py 的 5 个 setup error，加后全通过）。

## 最终全量运行（本机执行一次）

命令: `T2_PYTEST_ARGS="-q --deselect tests/core/test_core_integration.py::test_open_replay_performance_gate --deselect tests/ui/test_shell_smoke.py::test_offscreen_gl_context_creation" T2_TIMEOUT=7200 scripts/t2_qemu_regression.sh`
输出: `880 passed, 2 deselected in 1501.97s (0:25:01)`, script exit 0。
运行日志: /tmp/opencode/t2-qemu-regression.log（关键摘录已收录本文件）。
分包依据（ADRun度: 计划允许时间盒外记录子集+理由）: 2 项 deselect 均为上列
发现 2/3 的 emu 限定项，非产品回归；CI matrix 未改动（ADR-006:31-32 阶段 1 仅 T1）。
