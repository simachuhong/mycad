# M2-B 设计复审：对标 Solid Edge

日期：2026-11-03。对象：`docs/superpowers/specs/2026-11-03-m2b-part-sketch-design.md` 初版。

## 结论

**原位零件平面草图的方向成立；初版不能直接作为完整实施契约。** 查出两个提交/重放阻断项，以及需要明确的交互和验收缺口。本文只复审和修订设计，不代表产品功能已经实现、设计已获批准或通过 Solid Edge 实机对比。

推荐定位：**历史驱动的独立零件草图，借鉴 Solid Edge 的平面锁定和原位操作。** 保留 MyCAD 的 Bus、确认、冻结解和下游重建契约。不得把界面相似描述成同步建模能力相同。

## 对标依据与适用范围

本次在线核查 Siemens 官方资料；未运行 Solid Edge，也未验证其 2026 版本界面。ST3/ST4 教材用于区分基本语义，不作为最新版菜单、颜色或默认快捷键保证。

- [S1：Sketching，ST4](https://support.industrysoftware.automation.siemens.com/training/se/en/ST4/pdf/spse01510-s-1040_en.pdf)：第 5 章描述顺序草图先选平面、绘制、加尺寸关系并返回；第 6–8 章描述构造几何、IntelliSketch 关系推断和驱动/参考尺寸。构造几何不参与特征轮廓；推断关系可以随落点应用；参考尺寸不能直接改值驱动几何。教材第 4 章另述同步区域及开放轮廓。以上为能力语义摘要。
- [S2：Sketch plane locking，ST3](https://support.industrysoftware.automation.siemens.com/training/se/en/ST3/spse01510/planelock1a.htm)：区分命令自动锁面和手动锁面；锁面前有平面与方向反馈；手动锁面可越过显示边界；界面及树节点反馈锁定状态，列出 F3 操作。
- [S3：Fallouts of Sketch Based Features，2017](https://blogs.sw.siemens.com/solidedge/fallouts-of-sketch-based-features/)：区分顺序特征依赖草图与同步特征可脱离原草图；同步尺寸迁移及 Used Sketches 不应原样套入 MyCAD 的历史重放模型。
- [S4：Robot Claw Linkage 官方教程](https://media.plm.automation.siemens.com/solidedge/tutorials/robot-claw/text/Solid-Edge-Robot-Claw-1-Linkage.pdf)：第一页示范 F3 锁面、Ctrl+H 草图视图、数值绘制以及后续区域拉伸。这是工作流参考，不是本项目必须照搬所有快捷键的要求。
- [S5：Right-Click Commands in Solid Edge Part 4，2019](https://blogs.sw.siemens.com/solidedge/Right-Click-Commands-in-Solid-Edge-Part-4-Part/)：同步区域可直接推拉，另有尺寸迁移选项；这些应与显式顺序特征操作区分。

下面的处理方案是本次 MyCAD 设计建议，不是 Siemens 官方要求。

## 阻断项

### B1：把所有已有草图编辑都路由到创建命令替换，会破坏约束链

初版规定修改原 `sketch.create` ordinal 后完整重放。但 `geom/kernel.py::_apply_sketch_constraint` 会检查 `base_state_sha256 == current.state_digest()`，约束命令还保存完整冻结坐标。修改创建状态后，后续 `sketch.constraint.add/update` 的旧摘要及冻结坐标不能直接沿用；保留 entity ID 不足以解决问题。绕过摘要校验也不能解决旧解覆盖新编辑的问题。

**修正：** 已有数值尺寸编辑采用 `preview_sketch_constraint_update`，经隔离候选追加 `sketch.constraint.update@1`，保留既有历史，并重建消费者。无后续状态依赖的创建草图修订才可使用 `ReplayEdit`。任意已约束草图的加删实体、拖动和删除关系，仍需完整的修订命令契约，不能用“重放失败时拒绝”冒充已支持。

建议后续设计追加冻结草图修订命令：绑定当前摘要、保留存活身份、明确实体/约束增删、记录求解来源及完整接受状态、重建消费者并支持历史 undo/redo。命令 ID/版本、模式迁移及兼容测试尚未定案；本次不注册新命令、不改 ADR。

### B2：一次 `sketch.create` 不能承载承诺的全部草稿约束

`geom/kernel.py::_create_sketch` 目前只接受有限的初始尺寸和 inferred 水平/垂直/重合关系；例如 user `fixed` 不允许写入初始草图。`Sketch` DTO 可表达一个关系，并不等于创建 handler 接受它。初版“一条追加命令提交全部新草图”与固定、相切、平行等用户约束承诺不一致。

**修正：** 明确初始创建、后续关系命令和最终确认的边界。按 [ADR-010](../../docs/adr/ADR-010-sketch-solver-integration.md) 现有契约，显式约束逐条确认和冻结；在初始草图未确认时不能偷偷写模型。要实现“自由绘制、约束、修改、最后一次完成”的完整草稿体验，需正式设计原子提交包或新版本冻结草图命令，并说明取消、审计和历史撤销粒度。不能默默改变 ADR-010 或用未确认求解结果绕过校验。

## 交互复审矩阵

| 项目 | 初版缺口或差异 | M2-B 修订要求 |
|---|---|---|
| 建模语义 [S1/S3/S5] | 混合原位绘制与历史编辑，但未说明对标哪一种模式 | 历史驱动为准；草图保留并继续驱动拉伸；不承诺同步直接编辑、尺寸迁移或自动消耗草图 |
| 锁面 [S2] | 没有明确悬停、选定和锁定的区别 | 悬停显示平面和 U/V，点击或锁定操作后才激活；切换绘图工具保持工作平面；草稿非空时不能换面重解释已有坐标 |
| 视图 [S4] | 正视入口与锁面关系含糊 | 锁面与正视独立；新建锁面后默认正视，可旋转检查；显式正视按钮；快捷键只在视口焦点生效，不能抢输入框 |
| 工具退出 | Esc、右键、Enter 未定义 | Esc 撤回当前未完成图元/拖动，再退出工具；不直接丢整份草稿。Enter 只接受当前字段或工具步骤；“完成草图”和“取消草图”独立 |
| 推断关系 [S1] | 吸附被误解为持续约束的风险 | 单次取点捕捉与持久关系推断分开开关。仅草稿内可表达的水平、垂直、端点重合进入首包自动推断；显示符号，求解/验证后生效，可撤销 |
| 外部参照 | 显示的下游模型可能成为自己的上游依赖 | 本包外部锚点只一次取值、明确非关联。编辑草图时下游预演为只读上下文，不允许变成该草图的持久支撑或约束；关联投影仍属 M6 |
| 驱动/参考尺寸 [S1] | 数值输入、驱动、测量三种语义未划清 | 字段注明“本次取值”或“驱动尺寸”；尺寸显示驱动/参考状态；参考值只读并随几何刷新。不得把键入的坐标默认宣传为持续尺寸约束 |
| 求解诊断 | 仅“欠约束/冲突/无解”过粗 | 区分未求解、欠约束、DOF=0、冗余、冲突、不可用；未知 DOF 不伪造数字；可解欠约束允许完成；翻转/分支变化需可见确认 |
| 构造几何 [S1] | 首包未列入 | 增加普通/构造切换与线型区分；参与捕捉及适用约束，不参与实体截面 |
| 草图与截面 [S1/S5] | 未定义开放草图与不能拉伸的区别 | 合法开放草图可保存；拉伸才要求现有内核支持的有效封闭截面。定位开口、相交和分叉；不静默补线或借模型边闭合 |
| 树与拉伸衔接 [S3] | 未规定已使用草图的重新进入 | 树上定位草图、编辑、显隐和消费者；完成后选中该草图，提供独立拉伸入口；成功后仍保留其身份和可编辑入口 |
| 面支撑 [S1/S2] | 与 Solid Edge 常见选模型平面的流程有差距 | 如实列为阶段差距：首包主平面/已确认 datum；旧查询兼容不等于稳定面绑定，不能作为全面对标通过依据 |

## 必补验收

1. 一条可解、欠约束的开放线保存成功；普通实体拉伸被拒绝并指出开口；补闭合后成功。构造线不会改变拉伸体积。
2. 自动推断开启时，水平/重合关系在之后的合法拖动中保持；关闭时只有一次取值。外部捕捉不生成隐含跨特征关系。
3. 锁定 datum → 连续线 → 圆，工具切换不换面；画到 datum 显示边界外仍正常。Esc 只取消当前操作；非空草稿换面不会重解释坐标。
4. 旋转视图、正视、恢复投影和相机；数值框输入时快捷键不抢焦点。关系图标、尺寸状态不能只靠颜色区分。
5. 创建圆 → 半径约束 → 拉伸 → 后加固定关系 → 改半径；完整重建后体积正确，参考直径刷新，历史保留，undo/redo/重开不再次求解。
6. 单改创建命令导致旧摘要失效的反例必须拒绝；正式的完整修订路径则必须使同类合法编辑成功。两者不能共用“失败即安全”作为完成证明。
7. 草稿包含固定/相切等关系，确认包需有可表达且可重放的契约；取消在约定边界内零写入，成功保存后卸载求解器仍可重放冻结解。
8. 先验证无求解器仍可画普通草图；仅依赖求解器的动作禁用。DOF 未知、冲突和翻转分别呈现，不把 DOF=0 当唯一解。

## 本轮验证与交付边界

阅读了创建/约束 handler、`ReplayChangeSet`、草图 DTO、轮廓构建器、ADR-010 和已有真实内核测试。定向回归：

```bash
uv run --no-sync pytest tests/geom/test_sketch_constraints.py -q -k 'constraint_command_rejects_stale_preview_without_history_change or existing_dimension_update_preserves_later_relations_and_rebuilds_without_solver or existing_dimension_update_rolls_back_an_invalid_downstream_profile'
```

结果：**3 passed, 57 deselected**。这些验证现有约束与重建契约，不代表 M2-B 新交互已通过。此次只修改设计及审查记录，不重复执行全量四门。

另外执行了进程内真实内核探针（通过 `uv run --no-sync python`，未保存测试档案、未改产品代码）：

- 创建半径 5 mm 的圆，追加半径约束，再用 `ReplayEdit` 将创建命令中的圆心移至 `(2, 0)`。候选结果 `failed`，失败位置为 ordinal 1 的 `sketch.constraint.add@3`，原因 `constraint preview is stale; solve it again against the current sketch`。源历史与探针前相同，取消候选成功。
- 把 user `fixed` 圆心约束放入新 `sketch.create` 参数。注册 schema 即报 `ValidationError`，`constraints.0.kind` 不允许 `fixed`；源历史不变。即使绕过 schema，当前创建 handler 也不支持这类初始 user 几何关系。两项分别证实 B1 和 B2。

复审判定：交互补充可写入设计；B1/B2 的完整提交契约仍待落定，不能直接标记“设计通过、可完整实施”。它们不是由 Solid Edge 对标引入的新功能，而是初版已承诺的编辑和约束能力所需条件。
