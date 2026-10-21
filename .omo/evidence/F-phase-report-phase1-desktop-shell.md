# F 阶段终检报告 — phase1-desktop-shell（阶段 1 桌面壳）

日期: 2026-10-22 · 分支 phase1-desktop-shell · 头 4deee9b

## 结论

阶段 1 计划 16 个 todo 全部 [x]；主会话可直接验收范围内四门全绿、
合规绿线全过。**验收未完成的唯一硬项: CI 三平台绿（todo 13 机制记录）——
需要仓库所有者在 GitHub 打开 draft PR 触发（本会话无 GitHub token）**:
https://github.com/simachuhong/mycad/compare/main...phase1-desktop-shell

## F1 合规审计（可自动化部分，本机实测）

| 检查 | 结果 |
|---|---|
| tests/test_layering.py（T1 分层不变量） | PASSED（含于全量） |
| tests/test_scope_audit.py（21 项审计 + FORBIDDEN_CI_TOKENS） | PASSED |
| tests/test_notice.py（NOTICE 闭包单向断言） | PASSED |
| tests/test_adr_docs.py（ADR 必含/禁含 token + commit 尾钩） | PASSED（15 项） |
| 补丁 hash 基线（patch_hash.py）随 OFFSCREEN 主套件 | PASSED |
| 类型抑制计数（# type: ignore / # pyright: ignore 全树 grep） | 0 |
| ADR-005 商业墙（JT/Parasolid/ACIS… grep） | 0 命中 |
| cryptography 3.4 分发许可一致性（Apache-2.0/MIT/BSD 声明） | NOTICE 覆盖，test_notice PASSED |
| CI 组成（FORBIDDEN_CI_TOKENS=aarch64/arm64/qemu/loong 在 ci.yml） | 0 命中（T2/T3 证据皆在脚本与 .omo） |

## F2 全量四门（HEAD=4deee9b，本机 2026-10-22 实测）

- `uv run pytest tests/ -q` → **882 passed** in 140.13s
- `uv run basedpyright` → **0 errors, 0 warnings, 0 notes**
- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 187 files already formatted

## 已知限制（非阻塞，进报告清单）

1. **T2（aarch64）**：QEMU 回归 880 passed / 2 deselect / exit 0（25:01）。
   遗留三项 —— ① pyside6==6.12.0 aarch64 wheel 需 glibc≥2.39（manylinux_2_39_aarch64），
   低于 2.39 的信创发行版 `uv sync` 整体失败（已记 ADR-006 §3 修正 + uv 提示
   required-environments 可达 headless 恢复可装）；② NF-04 open 回放性能门
   （<1000ms）在 QEMU 下 1525–1760ms，需 T2 原生机复核；③ 离屏 GL 上下文在
   qemu-user 下创建失败（QOpenGLContext.create()=False），GL 渲染路径需 T2 原生机。
   证据: .omo/evidence/t2-qemu-regression-phase1-desktop-shell.md + scripts/t2_qemu_regression.sh。
2. **T3（龙芯）**：spike 决议 **no-go**（官方 PyPI 全历史 0 个 loongarch wheel ×4 包；
   loongnix 镜像仅 numpy≤1.8.2 cp36 / PySide6 6.2.0 cp37-38 loong 轮，cadquery/OCP 家族 0）；
   T3 降级战略路线，复评触发器三条记入 ADR-006 §5。
   证据: .omo/evidence/t3-loongson-spike-phase1-desktop-shell.md。
3. **CI**：功能分支不触发（ci.yml 仅 main push/PR）；draft PR 待用户操作（见上）。

## F3 手工 QA（见同目录 manual-qa-checklist 行清单）

由会话盲区决定：无桌面显示、无 aarch64/loongarch 实机、无 GitHub token。
已在本会话可执行的部分（CLI 四子命令、offscreen 全量 GUI 测试）均已实测通过。
