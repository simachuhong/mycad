# N1/N2 引用契约与拓扑演化原型、N6 局部尺寸及 STEP 验证

日期：2026-10-29。工作树基线沿用当日 Phase 2 审计；本记录只描述当前工作树增量，不代表远端 CI 或 P2-12/P2-19 全部关闭。

## N1：有限引用契约与验收矩阵

| 概念 | 契约 | 回归证据 |
|---|---|---|
| 查询引用 | 谓词（如最大 +Z 平面）每次按当前几何重新求解；显式 rank 只影响查询排序，不形成对象身份 | `test_max_face_is_requeried_from_predicate_after_size_change` |
| 绑定引用 | 绑定 `owner_feature + role + predicate + topology_id`；只在原 owner 与 topology generation 有效时解析 | `test_stale_topology_generation_reports_drift_and_parameter_location`、`test_live_reference_with_replaced_owner_reports_deleted` |
| 多候选 | 无唯一依据时返回 `ambiguous`，禁止回退到 rank/第一个候选 | `test_equal_maximum_faces_are_ambiguous_instead_of_rank_fallback` |
| operation-local 演化 | source/target 索引只在一次操作内定位；按原生 history 分类保留、修改、生成、分裂、合并、删除；缺少映射证据时用 `unknown` | `tests/geom/test_topology_evolution.py` |
| 重放与失效 | topology generation 变化后，旧 runtime binding 报 drift；不得静默跳到同类或同 rank 面 | `test_kernel_assigns_feature_ids_and_expires_refs_on_state_change` |

这是当前阶段的安全契约，不承诺持久设计身份。查询引用可以随参数变化而改选；绑定引用必须保持 owner/generation 或显式失效。现有 `SemanticFaceRef` 仍是 runtime 引用，不能保存为长期引用，也还没有由演化映射自动更新。

## N2：OCCT 操作内演化原型

后端无关 DTO 位于 `src/mycad/core/topology_evolution.py`，OCCT 调用和实体索引适配位于 `src/mycad/geom/topology_evolution.py`。适配器捕获 `BRepAlgoAPI` history 和 same-domain cleanup history，分别计算面、边的来源映射。关系分类依据具体来源：既有参数面变形为 `modified`；工具面贡献到结果记为 `generated`；一个来源产生多个目标为 `split`；多个来源落到同一目标为 `merged`；无剩余且原生报告删除才标记 `deleted`；无证据返回 `unknown`。

| 几何操作 | 覆盖情况 | 测试 |
|---|---|---|
| `feature.hole` / 草图孔 | 经 `BuildKernel` 捕获单次 Boolean cut 的面、边历史 | 切孔检查既有面保留/修改及工具面生成 |
| `modify.boolean_cut` | 经 `BuildKernel` 捕获最后一次成功 cut 的演化 | 槽切顶面一对多；整件切除时来源面删除 |
| Boolean fuse | helper 原型能追踪两个盒顶面合并到同一结果面 | 双盒融合多对一 |
| 面/边返回索引 | 分开按最终 faces/edges 编号 | 切孔边索引全部落在结果边界内 |

`last_topology_evolution` 仅表示最近一次成功操作；下一次成功的非 cut 操作会清空该值。原型不会持久化索引，也不会自动把输入 `SemanticFaceRef` 传递到后续命令；失败、歧义和未实现操作仍必须走现有错误/失效路径。圆角、倒角、布尔相交、阵列及多特征 lineage 尚未接入，不能据此宣称支持所有拓扑演化。

## N6：局部尺寸、undo 与 STEP

- `examples/parameter_perturbations.json` 的 108 条基线/扰动预期都含圆柱局部直径集合（无圆柱面的场景为空集合）。参数化场景通过当前 kernel 的圆柱面测量值检查该尺寸意图。
- 18 个受支持零件的 STEP 回读新增实体有效性、包围盒尺寸/中心和预期圆柱直径检查；与现有体积/实体数检查并行，不作 STEP 字节比较。
- 生命周期 undo 后先与“已修订命令链去掉最后一条命令”的独立重放前缀比较，再 redo 并断言扰动几何，避免把参数 amendment 的 undo 误当作历史撤销。

本轮加强的是已有圆柱面的直径，不代表已完成所有孔位、孔数或拒绝样本交换限制的矩阵；这些仍列为 P2-19/P2-12 尾项。

## 验证

最终定向验证：

- `uv run pytest tests/geom/test_topology_evolution.py tests/geom/test_semantic_selectors.py tests/geom/test_features.py tests/geom/test_sketch_holes.py tests/geom/test_face_selectors.py tests/scenarios tests/test_layering.py -q -x`：**216 passed**。
- 在最后补入“下一次成功的新建操作清空旧演化结果”断言后，`uv run pytest tests/geom/test_topology_evolution.py -q -x`：**5 passed**。
- `uv run ruff check` 与 `uv run ruff format --check`：本次改动的 8 个 Python 路径通过。
- `uv run basedpyright src/mycad/core/topology_evolution.py src/mycad/geom/topology_evolution.py src/mycad/geom/_b123_features.py src/mycad/geom/kernel.py tests/geom/test_topology_evolution.py tests/geom/test_semantic_selectors.py tests/helpers/step_roundtrip.py tests/scenarios/test_parameter_perturbations.py`：**0 errors, 0 warnings, 0 notes**。

该定向测试包括完整场景目录、拓扑/语义引用/面选择/孔特征测试和分层不变量；未运行当前候选集的全仓四门或远端平台 CI。
