# Metis 缺口分析 — phase0-mvp（规划师自行执行）

> Metis 子代理通道 4 次尝试全失败（3 个模型 ID 不存在 + gpt-5.5 超时零产出，bg_bde1e036），与 9/9 librarian 挂死同属本环境子代理基础设施故障。本分析由规划师按 Metis 六维方法自行执行；独立 Codex Momus（ARK 端点，deepseek-v4-pro）另跑，结论存 momus-codex-1.md。
>
> 对象：`.omo/plans/phase0-mvp.md`（417 行），2026-09-17。

## 1. 矛盾（CONTRADICTIONS）

- **C1（最重要）法兰中心孔与"参数化"验收矛盾 + `cut` 动词两义**：T11 脚本（plan:353）中心孔走 `modify.boolean_cut` 内联工具体，只有 4 孔走 hole_pattern；需求 §8 条件 1 要求内孔参数可改，且 feature.hole 单命令没有端到端用例（AC1）。同时 `cut` 既是 modify.boolean_cut 别名（T7 plan:261），cylinder 又有 mode=cut，CLI 表达未定。修复：法兰 5 孔全部走 feature.hole / feature.hole_pattern 谓词路径；布尔模式仅以键值 `mode=add|cut`（默认 new）出现；动词 `cut` 唯一映射 modify.boolean_cut，其自身测试用 box 工具体。
- **C2 pin 语法不一致**：Scope plan:36 `==7.9.3.1.1.*` 是无效 PEP 440；T1 plan:111 `>=7.9.3.1.1,<7.9.4` 正确。统一为后者。
- **C3 layering 守卫措辞冲突**：T2 plan:140 说 numpy/kernel 仅 kernel.py+tests/geom；T5 plan:208 允许 geom 包内拆 `_b123_ops.py`；T8 又要 geom io 模块。统一规则：**src/mycad/geom/ 包外任何 src 模块不得 import build123d/OCP/numpy；tests 仅 tests/geom 可直接 import**，geom 包内模块不限。
- C4 T2/T5 对 test_layering.py 的先后修改：依赖矩阵已 T5 blocked by T2，非矛盾，T5 验收须显式重跑守卫。

## 2. 缺失约束（MISSING CONSTRAINTS）

- **M1 SPDX 版权主体未定** → 固定 `SPDX-FileCopyrightText: 2026 MyCAD contributors` + `SPDX-License-Identifier: Apache-2.0`。
- **M2 内置命令注册方式未定** → 内置 8 命令在 app.py **显式 Python 注册，不走 entry_points**；entry_points 组仅供第三方插件（避免自举歧义）。
- **M3 bbox DTO 字段未定** → `BoundingBox(xmin,ymin,zmin,xmax,ymax,zmax)` + `size` 属性；golden 断言 size=(80,80,8) 且居中（±40）。
- **M4 空文档语义未定义** → 空态 solid_count=0/volume=0.0；对空几何导出 STEP/STL 抛 `EmptyGeometryError`（加入 core.exceptions 全集），T8/T10 各加失败用例。
- **M5 无 GitHub 远端时 Windows 证据** → T1 可记"workflow 就绪待推送"；但 Final F3 若无远端，必须把"Windows 未实测"写成**已知遗留**，禁止声称双平台已验证。
- **M6 examples 来源** → flange_script.txt / flange_plan.json 由 T11 手写、被验收测试引用，禁止生成器反录。
- **M7 Part 对象边界** → build123d Part 不离开 geom 包；取消"不透明 snapshot 给 formats"的说法，formats 调 geom 的 `export_step/export_stl/import_step(path)` 方法；跨边界只有 DTO 与路径。
- **M8 grammar 嵌套语法无完整文法** → 写死：对象用扁平点键 `target_face.surface=plane`、数组元素用扁平索引点键 `edges.0.curve=circle`（与校验错误点路径 holes.2.radius 同构）；方括号仅标量数组 `center=[0,0,0]`；pattern/depth 等枚举判别键 `depth.kind=through_all`。T3 docstring 给 ≥6 条完整示例并各配往返测试。
- **M9 redo 栈规则** → execute 任意新命令清空 redo 栈；T6 加测试。

## 3. 范围蔓延（SCOPE CREEP）

- S1 tessellation 无消费者：限定中立 Tessellation DTO + 单调性测试，**不输出文件、不碰 OpenGL**（T2 补禁令）。
- S2 插件夹具位置：future/bad 夹具只在 `tests/fixtures/plugins/`（测试期临时构建），demo 在 `plugins_examples/`；二者都不在主包 hatchling packages 内，不进 wheel。
- S3 metadata "任意保留键白名单"含糊 → v1 封顶六键：part_no/revision/material/source 必填四 + part_name/notes 可选二；余键 ValidationError。

## 4. 便宜可查但未查的假设

- A-i fillet/import_step 的 0.11.1 实测签名（尖刺只验了 volume/bbox/export）→ 计划已要求执行代理 REPL 实测为准，规划阶段不再追加研究。
- A-ii hatchling src 布局配置 → T1 执行时验证。
- A-iii Windows 中文路径编码 → 本机无法预验，reconfigure 兜底 + CI 用例 + M5 遗留机制。

## 5. 缺失验收（MISSING ACCEPTANCE）

- **AC1** feature.hole 无端到端验收 → 修 C1 后法兰 5 孔全走谓词路径，自动补齐。
- **AC2 "参数化"没有真正验收**：T11 参数表驱动须断言**同一 Document 改命令参数后整体重放**（不是新建文档），验证谓词在不同孔径/PCD 下选中同一组面。
- **AC3** demo.ping 输出形态 → 固定返回字符串 `pong`（Bus execute 返回值），测试断言；不引入通用结果对象。
- **AC4** cancelled 状态转移未点名 → 矩阵测试显式含 draft→cancelled、confirmed→cancelled 合法；done/failed 为终态。

## 6. 三大高杠杆默认的对抗式质询（CONTRARIAN GRILL）

- **D1 headless 边界 — 维持**。需求 §7 自定义阶段 0；§8 五条验收中 #2/#3/#5 可 headless 投影，仅 #4 skip。前提是 C1+AC2 必须修，否则"参数化"未被证明。
- **D2 重放 undo — 维持**，加量化护栏：T6 增加性能观测（重放 10 次法兰序列计时打印，不设硬门限，数据入证据），为 ADR-002 的 brep 缓存 v2 决策留基线。
- **D3 geom 封层 — 维持**。护栏：封层 API 表面最小（reset/apply/mass_properties/tessellate/export_*/import_*），Final F2 检查中立层没有镜像 build123d 概念大类。

## 回填处置清单

| 编号 | 落地位置 |
|---|---|
| C1+AC1+M8 | T3 grammar 文法、T5 hole 语义、T7 动词表、T11 脚本序列 |
| C2 | Scope 第 1 项 pin 文本 |
| C3+M7 | T2/T5/T8 layering 与 geom io 表述 |
| M1 | T1 SPDX 头 |
| M2 | T7/T9 注册方式 |
| M3 | T2 query.py + T11 golden |
| M4 | T2 异常全集 + T8/T10 用例 |
| M5 | T1 acceptance + F3 |
| M6 | T11 |
| M9+AC4 | T6 |
| S1/S2/S3 | T2/T9/T6 |
| AC2 | T11 |
| AC3 | T9 |
| D2 护栏 | T6 |
