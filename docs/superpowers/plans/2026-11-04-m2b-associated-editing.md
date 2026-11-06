# M2-B 独立草图与关联编辑 Implementation Plan

> **执行方式：** 使用 superpowers:executing-plans 逐项实施；每项先写真实行为测试并见到失败，再实现和验证。

**Goal:** 在零件三维视口中独立编辑可重放的平面草图，并推进基准关联的预演、重建与失效诊断。

**Architecture:** 草稿会话使用与二维工作台隔离的中立 `Sketch`；零件视口负责交互与显示，所有模型提交通过 Bus 和隔离候选。既有尺寸通过追加约束更新命令重建，草图结构和批量约束的持久化需要先定义兼容既有审计、冻结解及重放的版本化契约。

**Tech Stack:** Python 3.12、PySide6、build123d 0.11.1、OCCT 7.9.3、可选 PlaneGCS。

**Spec:** `docs/superpowers/specs/2026-11-03-m2b-part-sketch-design.md`；对标与提交风险见 `.omo/evidence/m2b-solid-edge-design-review-2026-11-03.md`。

**Acceptance（2026-11-04 用户确认）：** [Solid Edge ST10 操作验收基线](../../design/solid-edge-interaction-acceptance.md)，逐项执行 ST10-S01–S15 及综合样例。设计和验收均锁定 ST10；图标使用 MyCAD 自有设计。旧任务的自动验证结果不等于本轮 ST10 人工验收通过。

**后续顺序：** [ST10 三维建模审查与 TODO](../../design/2026-11-04-st10-3d-review-and-todo.md) 为当前源码盘点及后续排序；先修 R1–R3 并完成工具入口/选面流程，再做动态输入、画布尺寸、区域特征衔接与工具补齐。下列原始清单保留历史，不按未勾选框推定功能尚未开发；具体已有实现及未完成边界见该审查。

## Global Constraints

- core 不导入 Qt、CAD 后端或 numpy；ui 不导入 geom/后端。
- 使用当前工作区和既有修改，不创建会遗漏未提交依赖的隔离副本，不混入未经用户要求的提交。
- 所有持久模型修改经 Bus；历史、redo、审计、revision、dirty 和存档迁移均验证。
- 无求解器时普通草图仍可绘制；求解器结果不可用或引用失效不得伪装成功。
- 尺寸的局部几何和基准坐标必须分别处理；不使用临时 topology ID 作为永久引用。

## Review Focus

- 基准在草图已约束后变化：必须核对冻结解摘要与关联重放，不能静默跳过校验。
- 已提交草图结构修改：增删实体及关系不能复写旧求解结果或删除下游依赖。
- 候选过期/切文档：草稿、选择、相机和晚到结果不得泄漏到另一会话。
- 打开旧存档和求解器缺失：旧命令版本和冻结结果继续可重放。
- 失败/取消：草稿可修正，源模型、命令历史和 redo 不变。

## Task 1: 独立草稿状态

**Files:** Create `src/mycad/core/part_sketch_session.py`; test `tests/core/test_part_sketch_session.py`.

- [ ] 创建测试：独立草稿新增实体、撤销/重做，新操作清除 redo；修改不能改变初始 Sketch。
- [ ] 创建测试：删除实体时返回受影响约束并原子删除，撤销恢复两者；未知实体拒绝且状态不变。
- [ ] 实现 `PartSketchEditSession`：持有不可变 `Sketch`，提供 `replace_sketch`、`add_entity`、`delete_entities`、`undo`、`redo` 与 generation。
- [ ] 对改变 frame、sketch_id 和缺失引用的草稿拒绝并保持状态。
- [ ] 路径级 pytest、ruff、format、basedpyright。

## Task 2: 关联重放与冻结约束契约

**Files:** `src/mycad/core/sketch_constraints.py`、`src/mycad/builtin_commands/specs.py`、`src/mycad/core/bus.py`、`src/mycad/geom/kernel.py` 及对应测试。

- [ ] 建立基准→草图→尺寸→拉伸→修改基准的真实内核反例，断言保持局部约束、重建世界位置；旧历史不得被静默改写。
- [ ] 定义新版本约束命令的局部草图摘要与旧版本兼容方式，确保后续基准平移/旋转不把局部解错误判为过期；旧版本保持原行为。
- [ ] 对已有草图结构修订设计带基础摘要、冻结状态、引用验证和消费者完整重建的追加命令；验证失效、撤销重做、重开和无求解器重放。
- [ ] 对新草稿的多约束确认设计显式原子事务及审计粒度，遵从 ADR-010 既有约束；不将非法初始关系塞入旧 `sketch.create`。

## Task 3: 三维工作台交互

**Files:** 独立 `src/mycad/ui/part_sketch_workbench.py`、`src/mycad/ui/viewport.py`、`src/mycad/ui/main_window.py` 及对应 UI 测试。

- [ ] 主平面及已确认 datum 的锁定、UV、正视和退出视图恢复；不实例化二维对话框。
- [ ] 线、连续线、矩形、圆、弧；命中、选择、端点拖动、删除和草稿撤销/重做。
- [ ] 显示网格、网格吸附、对象捕捉和关系推断独立；数值输入不二次吸附，外部引用明确一次取值。
- [ ] 驱动/参考尺寸和适用约束经求解预览，分支变化和冲突可见；取消、切换文档与 stale 回调安全。
- [ ] 草图确认后从树定位编辑并独立拉伸；支持开放草图保存及封闭截面错误定位。

## Task 4: 关联编辑与失效处理基础

- [ ] 覆盖基准修改传递到草图及全部消费者，展示受影响对象，预览失败指明命令、ordinal、引用及原因。
- [ ] 验证隐藏基准与引用失效的区别；删除/失效引用不猜测替代对象，拒绝部分提交。
- [ ] 验证多文档、存档重开、上下游编辑、错误恢复、undo/redo 和 stale 授权。

## Task 5: 最终集成

- [ ] 更新项目文档与能力边界；执行改动路径 scoped 四门及最终全量四门。
- [ ] 执行真实桌面操作验收；若当前环境不支持，记录未完成项目，不以自动测试代替。
- [ ] 按 ST10-S01–S15 逐项记录版本/模式、ST10 依据、MyCAD 实操证据及差异；未核对或未实现的子项保持未通过。
- [ ] 执行 40×30×10 mm 矩形拉伸、改宽到 50 mm、保存重开及撤销/重做的综合样例，并由用户确认最终操作验收；例外须明确记录用户接受结果。
