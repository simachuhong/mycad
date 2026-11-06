# P2-19 代表零件场景具体化与回归证据

日期：2026-10-29。工作树基线：`ba2f539`；本记录描述当前未提交工作树的定向验证，不冒充远端 CI。

## 交付范围

- 原 78 条 `gated` 多命令记录已补为完整命令链、显式命令版本、零基目标序号、可定位参数路径、基线/扰动值和数值化几何预期。连同原 30 条，现为 108/108 条 `executable`。目录测试禁止 `params: null`、错误目标 ID 和无数值断言的记录回归。
- 13 类多命令样本分别覆盖法兰、轴/套、安装板、端盖和边界件。六条扰动并非复制标签：在可用范围内修改基体、孔径、阵列或局部凸台尺寸，并重放下游特征。
- 修复两个实质建模问题：`shaft-cross-hole` 原目录声称受支持，但孔实现只允许平面，现允许在圆柱侧面给定显式点并沿局部法线钻径向通孔；`cover-raised-rim` 原链只有叠加圆柱，不能形成环形凸缘，现增加盲孔切除后再打基盘阵列孔。
- 每条扰动检查有效单实体、体积、包围盒、可选引用、原始时间戳不覆盖、amendment 追加及恢复。每个受支持样本另执行创建、选择、改参、体积测量、undo/redo、`.mc.json` 保存重开与 STEP 体积/实体数往返。

## 独立几何预期与公差

圆柱/盒及轴向通孔、均布孔、两段同轴加料、环形凸缘和薄壁切除使用解析体积与外包围盒。横向孔的两个正交圆柱交体积由独立 Simpson 积分得到。OCCT 横向布尔体积与解析值约差 `0.008 mm³`；仅此场景使用 `0.02 mm³` 体积容差与 `1e-5 mm` 包围盒容差，其余体积断言为 `1e-7 mm³`。STEP 按体积公差比较，不比较字节。

## 验证

- 红阶段：目录测试对原 `gated` 状态失败；首轮完整执行暴露横向孔解析体积/OCCT 差及包围盒数值公差，修复后转绿。
- `uv run pytest tests/scenarios -q`：131 passed（包括 108 条扰动和 18 条受支持零件生命周期）。
- `uv run pytest tests/geom/test_features.py -q`：47 passed；覆盖圆柱侧面径向孔和缺少显式定位点的拒绝。
- `uv run ruff check`、`ruff format --check`、`basedpyright` 限定改动的 Python 路径执行；结果见本次会话最终验证输出。

本证据只证明当前样本的参数重放与选取能力。P2-12 要求的面分裂/合并演化映射与引用修复仍是独立开放项；按照主计划的硬依赖，P2-19 的正式勾选需待该引用门关闭，不能用 108 条通过替代它。

## 后续源码复核补记

原 184 项定向通过记录保持有效。当前“可选引用”断言实际为候选列表非空，未验证旧绑定在改参后仍指向同一设计对象；自动生命周期主要测量整体体积，STEP 回读只比较实体数与体积。P2-19 还需局部尺寸/位置、undo 中间态、交换后有效性及引用身份断言。下一步与 P2-12 联合收口，详见 [进度报告 N1～N6](../../docs/phase2-progress-and-next-tasks-2026-10-29.md)。

## 2026-10-29 N1/N2/N6 增量

后续工作已补足 operation-local topology 原型，并加强 P2-19 局部尺寸和 STEP 断言：108 条基线/扰动预期均含圆柱局部直径集合；18 个受支持零件 STEP 回读检查有效性、实体数、体积、包围盒尺寸/中心和圆柱直径；undo 结果与编辑后命令链去掉末条命令的独立重放前缀比较，再验证 redo 几何。引用契约和演化关系证据详见 [N1/N2/N6 实施记录](task-N1-N2-N6-topology-2026-10-29.md)。

定向组合验证：`uv run pytest tests/geom/test_topology_evolution.py tests/geom/test_semantic_selectors.py tests/geom/test_features.py tests/geom/test_sketch_holes.py tests/geom/test_face_selectors.py tests/scenarios tests/test_layering.py -q -x`，**216 passed**。P2-19 仍为 partial：持久绑定引用、完整孔位/孔数矩阵和拒绝样本交换策略未完成。
