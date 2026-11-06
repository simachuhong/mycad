# ADR-016 — 空间基准与档案 v6

状态：2026-11-02 用户授权 M0/M1 开发；v6、候选迁移和基准命令的开发 API 已实现，最终集成验证见[实施记录](../../.omo/evidence/m0-m1-spatial-foundation/acceptance.md)。独立三维草图 GUI 属于后续 M2。设计依据：[三维建模基础框架修订](../superpowers/specs/2026-11-02-3d-modeling-foundation-design.md)。

## 决策

沿用 ADR-014 的命令实例身份和 ADR-001 的 Bus 及有序重放。基准不是 BREP 几何，基准定义保存在版本化命令参数中，求值表是从历史派生的运行状态。世界坐标系为不可删根。文档或候选中的激活坐标系与相机只影响输入显示，不参与既有命令求值。

新能力使用档案 v6；v1–v5 读取和语义不变。v6 沿用 v5 的所有命令 instance_id 与审计字段。打开旧文件不升级。首次使用需要 v6 的命令时，候选中明确指定目标版本，预演成功并确认后连同历史原子提交；取消/失败保留源文件版本、命令、审计、dirty、redo 和几何状态。v4 迁移必须同时申请活动和 redo 命令身份；已存在 v5 身份不得被重分配。不能静默将 v6 文档保存为旧版本。

## 命令与引用契约

M1 启用原保留的 `datum.*` 命名空间：`datum.coordinate_system.create@1` 输出 role `coordinate_system`；`datum.plane.create@1` 输出 role `plane`。身份为当前文档中创建命令的 canonical instance_id 与固定 role；显示名及运行时拓扑编号不作身份。`sketch.create@4` 支持基准引用和兼容的旧草图参数分支；未指定版本且使用旧 frame 参数时，Bus 继续记录 @3，避免对旧脚本隐式迁移。@4 要求 v6。

引用形式：`{"kind":"world"}`；`{"kind":"coordinate_system","source_instance_id":"<32位小写hex UUID>","role":"coordinate_system"}`；`{"kind":"datum_plane","source_instance_id":"<32位小写hex UUID>","role":"plane"}`。仅能引用之前已求值的正确类型输出，缺失、前向、循环和类型错误均拒绝。已有受支持 bound-face 按 ADR-015，M1 主/偏置平面优先支持 datum 链；绑定面支持需几何适配与专门测试。

坐标系保存父引用、父系中的原点和三个正交右手单位轴。以列向量计算 `T_world_child = T_world_parent × T_parent_child`；禁止缩放、镜像和非有限值。主平面 XY、XZ、YZ 采用现有 WorkPlaneFrame 约定，XZ 的 U=+X、V=-Z、N=+Y，不能因旧文档字符串错误而翻转已有模型。偏置记录有符号 mm，沿父平面 N 平移，继承 U/V/N。草图局部尺寸以 UV 存储；关联支撑的面内位姿只持久化一次，由父框架求值。

## M1 参数形式

- 坐标系命令含 `name`、`parent`、`origin_mm`、`x_axis`、`y_axis`、`z_axis`。
- 基准平面命令含 `name` 与 `construction`：`principal` 使用 `coordinate_system` 和 `plane`（xy/xz/yz）；`offset` 使用先前 datum `plane` 和 `distance_mm`。
- 关联草图 `sketch.create@4` 用 `support` 代替顶层 `frame`；其字段为 `plane`、`offset_uv_mm`、`rotation_deg`、`flip_normal`，图元、图层和约束延续 @3。局部数据和支撑定义随命令保存，求值 frame 不单独持久化。
- M1 支持偏置自 datum 平面；关联绑定模型面、角度/三点等构造仍属后续范围。新增 API 与既有候选校验接受 `ReplayChangeSet(..., target_archive_version=6)`，兼容原有 `upgrade_to_v5` 调用。

## 开发接口示例

先使用 `ReplayChangeSet((), (ReplayAppend("datum.coordinate_system.create", 1, params, "local"),), False, target_archive_version=6)` 创建候选，预演成功后经 `authorize_commit` / `commit` 确认。读取已提交的命令 `instance_id`，供下一条 `datum.plane.create` 的来源引用；后续用 `sketch.create` 显式指定 `version=4` 建立关联草图，再使用既有 `feature.extrude` 引用草图 ID。

这是一条经 Bus 的开发接口，不等于已有坐标系或基准平面 GUI。非显式指定版本时，旧 `frame` 草图仍使用 @3；带 `support` 的草图使用 @4。v6 的 v4 草图 schema 保留旧 `frame` 分支，保证 CLI 校验/序列化可理解既有参数；版本最低档案门槛仍为 v6。

## 迁移与生命周期

候选的来源文档、修订、session、generation、修改摘要和一次授权继续按 E3-A 校验。提交必须对格式升级与全部命令采用整体成功或失败语义，不能通过直接修改 Document 绕过 Bus。加载、撤销/重做、内核 reset、候选预演、打开的状态替换、草图消费者重建及故障回滚均重建或整体替换基准求值表。嵌套引用的版本上限必须以容器版本为上限递归校验；v6 可包含受支持旧版来源，旧版容器不能包含 v6 来源。

不改变旧查询面语义，也不把查询面自动转换为稳定绑定；分裂/合并面不允许靠索引或最近面回退。原子提交不增加整次多处历史编辑的一步撤销语义。新增关联草图命令、候选与档案 schema 的精确字段在 M1 可执行测试中锁定。
