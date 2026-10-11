# 阶段 1 backlog（阶段 0 交付时登记的缓办项）

来源：Final wave 四份证据（`.omo/evidence/final-1..4-phase0-mvp.md`）的非阻断观察 +
CI 收尾三轮修复的实测沉淀。登记日期 2026-10-12（三平台全绿 run 38162917017，
HEAD=6086b29 之后）。本文件只登记不定档；排期与拆解在阶段 1 规划时进行。

## 流程 / 基建

- [ ] **镜像 uv.lock 守卫**：CI 加检查 `uv.lock` 内不得出现 pypi.org 以外的 registry
  （国内镜像路径会改写 lock，现仅 README 人工警示）。来源 F3 遗留风险。
- [ ] **`mycad plugins` 空输出可用性**：无插件时打印一行人类可读提示（exit 0 契约
  不变）。来源 F3 遗留风险。
- [ ] **分支策略回归**：阶段 0 收尾的 CI 修复经用户指示直推 main（记录在案）；
  阶段 1 按 plan Commit strategy 回归「单一工作分支 + 单 PR 合入、禁止 main
  直推」。来源 plan:528-534 + ledger final-verdict。

## 静态分析 / ruff（来源 F2；正式偏差表见 pyproject.toml 配置注释）

- [ ] PT（21 处，PT001/PT018 纯风格）评估开启。
- [ ] PL（138 处，103 为 PLR2004 测试字面量断言）评估开启或测试树范围豁免。
- [ ] `_b123_ops.py` 6 个内部函数补 docstring。

## 守卫覆盖性（来源 F4 复查 M1-M25 状态表；全表见 final-4 复查章节）

- [ ] M1：GUI 禁词表补 tkinter / wx。
- [ ] M3 / M7（视口、agent/ 内容边界）：现由文件内书面声明承担（GAP 2），机器化。
- [ ] M8-M12（网络 / 打包 / 发行禁令）：现为标识符 tripwire（WEAK），评估升级为
  AST 级断言。
- [ ] M13 / M14：驼峰拼接（JTProvider / ElementMapper 类命名）绕整词匹配；检测器
  分词升级。
- [ ] M17-M19（subprocess / seccomp 等动态面）：静态不可穷举（WEAK），显式接受或
  引入运行时探针。
- [ ] M25：保留命令 id（chamfer/shell/union/intersect/pattern_linear/mirror/draft/
  sweep/datum.*）加「未注册」机器断言。
- [ ] N5 模式推广：遍历型守卫统一加 `assert scanned > 0` 元断言（F2 的
  scan_suppressions 已实装，模式需推广到其余遍历守卫）。

## API / 设计（来源 F1 非阻断观察）

- [ ] N1：NamedGroup 已删 list→tuple 运行时归一化（tuple 标注为诚实契约）；二选一：
  入参改 Sequence + 显式 `tuple()`，或在 ADR-002 注明由静态类型承担。
- [ ] N2：PT/PL 与计划 :131 的偏差已记录未正式消解，需计划所有者签字接受。

## CI / 跨平台（收尾三轮修复；已生效项为备案非待办）

- （已生效）junitxml → 注解自报告链路（3c923b4）；`.gitattributes` LF 根治
  （5563e38）；测试 subprocess 固定 utf-8（3374d3a）；NOTICE 平台差异段覆盖
  Windows 闭包 colorama 入 / pexpect 出（6086b29）。
- [ ] 新增依赖时，NOTICE 测试对账的平台条件闭包差异仍需人工确认（Linux 侧
  `uv tree` 看不见 `sys_platform` 条件分支）。
