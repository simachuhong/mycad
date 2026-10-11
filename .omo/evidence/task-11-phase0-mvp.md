# Task 11 — 法兰验收资产 + examples + NOTICE/README 收尾（Phase-0 MVP）

## §T11-pre 前置基础设施缺口修复与决策（主会话，2026-10-11）

T10 完成后对 T11 做前置风险排查，发现三处「照计划原文实现必红」的缺口。本节记录
修复与用户决策，T11 执行者据此落地，**不要**再按计划原文的旧预期写断言。

### 缺口 1：`uv tree --package mycad --no-dev` 不过滤 dev 依赖（已修）

- 根因：dev 依赖原声明在 `[project.optional-dependencies]`（extra）。`--no-dev` 只对
  PEP 735 `[dependency-groups]` 生效，对 extra 无效，故输出含 `(extra: dev)` 子树。
- 实测后果（修复前）：命令输出 61 个分发名，真实运行时闭包只有 46 个；多出的
  `ruff`/`pytest`/`basedpyright`/`hatchling`/`nodejs-wheel-binaries`/`packaging` 会同时
  打穿两个 T11 断言——NOTICE「闭包每名必列」会被迫收录开发工具，且 `packaging` 本身
  在 F4 违禁名单里，`test_runtime_closure_clean` 直接红。
- 修复（用户决策：迁 dependency-groups，保留计划钉死的命令字面量按原意生效）：
  `pyproject.toml` 的 `[project.optional-dependencies] dev` → `[dependency-groups] dev`
  （内容逐字不变）；`uv lock` 重锁；CI `uv sync --frozen --extra dev` → `uv sync --frozen`
  （uv 默认同步 dev 组）。README/AGENTS 只用裸 `uv sync`，无需改动。
- 验证：修复后 `uv tree --package mycad --no-dev` = 47 名（46 依赖 + mycad 自身），
  零 dev 名、零 `packaging`，与 importlib.metadata 独立推导的运行时闭包逐名一致；
  `uv sync --frozen` 后 ruff/pytest/basedpyright 均可用；全量四门 767 passed。

### 缺口 2：`.gitignore` 缺六个验收产物条目（已修）

- 计划 T11 验收称「这些路径同时已被 T1 `.gitignore` 逐行忽略」——实际 T1 未交付该规则。
- 修复：`.gitignore` 增六条根锚定规则（`/flange.step` `/flange.stl` `/flange.mc.json`
  `/examples/flange_plan.step` `/examples/flange_plan.stl` `/examples/flange_plan.mc.json`）。
- 验证（含反向自证）：touch 六路径后 `git status --porcelain` 不含任何 flange 行；
  额外 touch `examples/NOT_IGNORED.txt` 后 `-uall` 下出现 `?? examples/NOT_IGNORED.txt`。
- **T11 实现提示**：`git status --porcelain` 默认把未跟踪目录折叠为 `?? examples/`，
  反向自证断言必须加 `-uall`，否则看不到具体文件名（本次排查实际踩过一次）。

### 缺口 3：OCCT 许可证归属——实测与计划预期不符（决策已定，T11 落地）

- 实测：`cadquery-ocp-novtk` 7.9.3.1.1 的 METADATA 声明 `License: Apache-2.0`
  （classifier 同为 Apache），**与计划预期的「LGPL 系列」不符**；wheel 内
  `cadquery_ocp_novtk.libs/` 捆绑 46 个 OCCT 7.9.3 原生库（libTKernel/libTKFillet/…），
  且 **wheel 内不附带任何 OCCT 许可证文本**（`dist-info/sboms/auditwheel.cdx.json`
  只列 libfreeimage/libtiff/libopenexr 等被 auditwheel 吸入的系统库，不含 OCCT 条目）。
- 性质：METADATA 的 Apache-2.0 覆盖的是 OCP 绑定代码；被捆绑分发的 OCCT 二进制上游为
  LGPL-2.1 + 例外条款。NOTICE 若只写 Apache-2.0 属低报分发义务。
- **用户决策（2026-10-11）**：NOTICE 对该组件**分两行**归属——
  ① OCP 绑定代码 Apache-2.0（注明来源=分发包 METADATA 实测）；
  ② 捆绑的 OCCT 7.9.3 原生库 LGPL-2.1 及例外条款（注明上游事实 + wheel 未附许可证文本
  这一取证边界 + 独立原生库/动态加载边界）。
  `tests/test_notice.py` 的断言改为**核对这两项同时在场**，不再做「实测字符串属于 LGPL 族」
  的单值比对（该比对按计划原文必然失败，是计划预期与上游实际不符，非实现缺陷）。

### 附：NOTICE fail-closed 取证预研（46 包，T11 直接复用）

- 44 包可从 METADATA `License` / `License-Expression` / classifier 直接取得 SPDX 标识。
- 需走「读 LICENSE 文件取证」路径的恰好 2 个：
  - `ocpsvg`：METADATA 无 License 字段；`ocpsvg-*.dist-info/licenses/LICENSE` 为
    Apache License 2.0 全文 → **Apache-2.0**。
  - `ptyprocess`：METADATA 字面 `License: UNKNOWN`（触发计划的占位禁律）；
    classifier `License :: OSI Approved :: ISC License (ISCL)` 且
    `ptyprocess-*.dist-info/LICENSE` 首行自述 ISC → **ISC**。
- 观察（非违规，记录备案）：运行时闭包经 build123d 引入 `requests`/`urllib3`/`certifi`/
  `idna`/`charset-normalizer` 与 `ipython`/`scikit-learn`。F4 只禁 `src/` 内网络 import
  （src 实测干净），闭包存在不构成范围违规，但属供应链面事实，NOTICE 需逐名列出。
