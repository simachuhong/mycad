# E2-B 绑定面孔验收

日期：2026-11-02。基线 `ba2f539` 加先前未提交的 N1/N2/N6/E1/E2-A 成果；复用当前 `codex/phase2-foundation` checkout。只评价本次增量，未提交、推送或发布。

## 交付与边界

- `feature.hole@3` 保留 @1/@2 查询/草图语义，仅新绑定分支要求显式 v5 与绑定能力内核。旧格式不被普通孔命令自动升级；旧 handler/kernel 不会静默执行绑定。
- `BoundFaceRef` 持久化当前文档的命令实例 UUID + box 六平面或 cylinder 顶/底角色。原生操作的精确输入/输出负责重建有限 lineage；结果面下标、运行时拾取 ID 和 rank 不充当持久身份。
- 局部孔位以来源原始面中心及固定方向构造，裁切不改变框架；改动来源尺寸/位置会重新构造框架。点必须在当前有限面内。继承的 center/point 保持原意。实际切孔复用现有孔径/深度与 Boolean 实现。
- 支持 primitive new/add/cut、inline cut、查询/草图/绑定孔的有限后继。唯一 preserved/modified 且平面不漂移时继续；分裂、合并、删除、未知 history、unsupported operation 等明确拒绝。cut 工具生成面、圆柱侧壁不绑定。
- `interactive_face_binding(TopologyId)` 使用精确当前面，拒绝过期、其他内核及无来源拾取。候选替换和草图内部再生保留配对的 Part/原生面映射。来源快照在自己的隔离环境重放，不把来源面角色注入工程图宿主。
- Bus 错误带命令、历史序号、参数路径及原因；非法 canonical UUID 在 handler/reset 前被拒绝。失败上游编辑恢复历史、审计、几何及 redo。

产品决策见 [ADR-015](../../../docs/adr/ADR-015-bound-face-hole.md)。桌面默认仍为 v4；升级确认、绑定拾取产品流程与失效修复仍属于 E3。不是通用拓扑命名，不关闭 P2-12/P2-19，也不声明与 Solid Edge 等价。

## 反例与审查

先以 latest hole 仍为 @2 的测试失败确认真实消费者尚未接入。实现后，检查实际圆柱孔壁中心、半径与轴向范围，不只检查实体体积。覆盖所有八种面角色和翻转方向，两个分离实体同尺寸/尺寸反转，非对称裁切、两次 cut、primitive cut、重放改参、保存重开、undo/redo、Save As redo、隔离预览与工程图来源。

独立审阅发现 malformed 32 字符 UUID 通过 schema 长度检查后在后端抛未定位 ValidationError。新增 Bus/加载两项反例先失败，再通过共享 DTO 前置校验修复。新命令的失效 ordinal 缺失也先由断言复现，再在 Bus 补当前历史序号。

扩大回归发现旧 UI 表单在新增根分支后，不完整值无法唯一确定查询/绑定分支。选面回填按真实 selector 的 schema 选择分支，保留其他未完成字段。复审进一步用“空表单/diameter=0”复现缺口，6 组参数反例中 4 FAIL/2 PASS 后修复；现在 6 组均通过。最终提交仍进行完整参数校验。复审最后未发现新增实质性问题。

兼容性回归还修复了旧 CLI history 因 DTO 新字段输出 `instance_id=None` 的泄漏，v1～v4 继续省略该字段，v5 则保留真实 ID 与绑定参数。已有测试中仅更新两个最新版本期望和 UI 分支列表；open 原子性测试的故障注入从旧 apply 迁移到实际使用的 apply_with_context，保留失败次数及活跃文档不变断言。未削弱旧 schema、layering 或类型抑制检查。

## 验证

- 最终新增 core/真实几何功能集：**36 passed，20.50s**，见 [JUnit](junit.xml)，0 failures/errors/skips。命令：`uv run pytest tests/core/test_bound_refs.py tests/geom/test_bound_face_holes.py -q --junitxml=.omo/evidence/e2b-bound-face-hole/junit.xml`。
- 扩大定向回归中的 core/commands/builtin 已完整通过；该轮在 app 旧注入点处停止前累计 726 passed。修正注入及 CLI 兼容后，后续集合 **397 passed，154.39s**：`tests/app tests/cli tests/plugins`、command_identity/features/kernel_primitives/topology_evolution/sketch_holes/viewport_snapshots/document_reference_replay、layering/scope audit。
- UI 首轮在旧 hole 版本断言处停止前 60 passed；修正断言后剩余及相关集合 **48 passed，29 deselected，104.98s**，涵盖参数表单、Save As session、CLI tab 及剩余建模交互。表单末次修复后完整 `tests/ui/test_parameter_forms.py` **16 passed，13.44s**。这些批次有重叠，不相加为唯一测试总数。
- 本轮 20 个 Python 路径的 ruff check / format check 均通过，basedpyright 为 0 errors / 0 warnings / 0 notes。git diff --check、文档本地链接与 JUnit 计数检查通过。无依赖变更或类型抑制。

没有重复执行已确认的其他任务，也没有执行全仓四门或远端三平台 CI；最终阶段集成与人工平台验收仍待后续。未创建新 worktree，保留已有未提交文件；测试只使用 tmp_path，没有关闭用户程序或改动用户建模文件。
