# T3 LoongArch64 spike — go/no-go conclusions (todo 16, 阶段 1 末)

**决议: no-go**（T3 降级为战略路线；阶段 2 不纳入 T3 工程承诺；记 ADR-006 §5）

## 探测命令与输出（全部本机 http 探测，未购硬件、未编译、未入 CI）

1. 官方 PyPI JSON API（`https://pypi.org/pypi/<pkg>/json`，2026-10-22）:

   - `cadquery-ocp-novtk`: 全部历史 release 中 loongarch 文件数 **0**
     （最近版 7.9.3.1.1 / 8.0.1.0.0 / 8.0.1.1.0 的 linux wheel 仅 x86_64 / manylinux_2_31_aarch64 / 8.0.x 降为 manylinux_2_28_aarch64）。
   - `build123d`: 全部 release loongarch 文件数 **0**（最近 0.8.0 / 0.9.0 / 0.9.1 连 aarch64 wheel 也没有——纯 Python 包，sdist 可装）。
   - `PySide6`: 全部 release loongarch 文件数 **0**（aarch64 为 manylinux_2_39）。
   - `numpy`: 全部 release loongarch 文件数 **0**。

2. 龙芯镜像 `pypi.loongnix.cn`（devpi，stage 路径探测：
   `/loongson/pypi/+simple/<pkg>/` 命中 200；`/simple/<pkg>/` 302-404）:

   - `numpy`: 4355 文件中 loong 246 —— 但最新仅到 **numpy-1.8.2-cp36 linux_loongarch64**
     （龙芯早期轮，停更于老 ABI 时代）。
   - `PySide6` / `shiboken6`: loong 仅 **6.2.0-6.2.2 cp37/cp38 linux_loongarch64**
     （2021 年 Qt 6.2，无 cp312；对本仓 pyside6==6.12.0 pin 无用）。
   - `cadquery-ocp-novtk` / `cadquery-ocp` / `ocp` / `build123d`: loong **0**
     （cadquery 系根本没有 loongarch64 构建，只有上游 aarch64）。

3. 源构建 OCCT/OCP 时间盒评估（文献，不实际编译）:
   OCP 绑定需要 OCCT 全 C++ 构建器 + cadquery/OCP 的 pybind/nanobind 胶水编译矩阵
   （多 Python ABI），上游无 loong64 CI 构建；龙芯社区未见公开维护的 OCP loong64 产物。
   评估为高成本长周期项（OCCT 构建本身为小时级、OCP 胶水需逐 ABI 维护），
   按 ADR-006 R8"最坏降级战略路线"处理。

## 决议理由

- 硬依赖通道不存在：OOCT 绑定（cadquery-ocp-novtk，仓库内 pin）无 loongarch64 wheel
  （官方 + 龙芯镜像皆 0），PySide6 的 loong 轮停留在 Qt 6.2 / cp37-38，
  与本仓 Python 3.12 + Qt 6.12 形态不兼容——即 headless 与 GUI 两半都不可直装。
- go 判据（复评触发器，记入 ADR-006）:
  (a) cadquery-ocp(-novtk) 上游或龙芯镜像出现 cp312 loongarch64 wheel；
  (b) PySide6 ≥6.8 出现 loongarch64 wheel;
  (c) 龙芯 LatX x86 二进制翻译可跑 manylinux x86_64 闭包（未测验证通道，无硬件不算 go）。
- 无-go 期间: 不购硬件、不进 CI（FORBIDDEN_CI_TOKENS=aarch64/arm64/qemu/loong 红线维持）、
  文档对外不承诺 loong64 支持。

## 与 todo 15（T2）关联

todo 15 发现 pyside6==6.12.0 aarch64 wheel 需 glibc≥2.39（manylinux_2_39_aarch64），
ADR-006 §3 基线声明同步修正——Linux 壳依赖的 glibc 地板 2.39 vs 2.31 分层已在本 ADR 记录。
