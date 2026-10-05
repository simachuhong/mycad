# T5 收尾任务：修复 hole_pattern 极坐标角度语义（3 个失败测试）+ 补写 evidence

你是 MyCAD 项目的 geom 特征层收尾代理。前任代理已完成 95% 交付（125/128 测试绿），
死于用量中断。你只需修 3 个失败测试 + 补 evidence 文件。**这是机械修复任务，设计已冻结，禁止重新设计。**

## 第一步（必做）

```bash
cat /media/sima/Data/projects/MyCAD/.omo/start-work/wave2-prompt-T5-finisher.md  # 本文件
cat /media/sima/Data/projects/MyCAD/.omo/start-work/wave2-prompt-T5.md  # 原始 T5 规格（只读参考）
```

## 现状（勿重查）

- 已交付：src/mycad/geom/profiles.py（107 行）、src/mycad/geom/_b123_features.py（533 行）、
  tests/geom/test_features.py（454 行）、src/mycad/geom/kernel.py（+11 行接线）。
- `uv run pytest tests/geom/ tests/test_layering.py -q` → **3 failed, 125 passed**。
- 失败的三个测试（全部在 tests/geom/test_features.py）：
  1. `test_hole_pattern_plus_z_centers_follow_global_polar_angles`
  2. `test_hole_pattern_start_angle_90_puts_first_hole_on_plus_y`
  3. `test_hole_pattern_count4_centers_match_flange_bolt_circle`

## 修复规格（计划 round7-3 冻结语义，逐字遵守）

hole_pattern 的 polar 分布使用**全局 XY 角度系**：
- `start_angle_deg=0` 指向 **+X**，角度增长朝 **+Y** 逆时针。
- 第 i 个孔中心（i 从 0 计）：`angle = start_angle_deg + i * 360/count`，
  `center = (face_center.x + radius*cos(rad), face_center.y + radius*sin(rad), face_center.z)`
  （z 用面心 z；孔轴方向随面外法向，不改角度）。
- **−Z 面不镜像**：−Z 面上的 pattern 角度系与 +Z 完全一致（同一公式），
  仅孔轴方向随 −Z 外法向翻转。
- 斜面（|n·ẑ| < 1−1e-9）已被前置校验拒绝（pattern-target-not-horizontal），与本修复无关。

先运行三个失败测试看具体断言差异（`uv run pytest tests/geom/test_features.py -q -k "hole_pattern" `），
再修 `src/mycad/geom/_b123_features.py` 中的角度计算。**禁止修改测试来迁就实现**；
若你认为测试本身与上述规格冲突，停下来在最终消息中报告 BLOCKED + 理由，不要动测试。

## 硬性纪律（反停摆，机械遵守）

- 每回合恰一个小动作；单次文件写入 ≤100 行；用 edit 工具做小修改而非重写整文件。
- 禁长篇设计推理——设计已冻结，只做机械转写与修复。
- 每完成一步立即落盘验证（跑相关测试）。

## 范围（白名单，越界即违规）

- 可改：src/mycad/geom/_b123_features.py、src/mycad/geom/kernel.py（仅当接线需要）、
  tests/geom/test_features.py（仅当发现测试与冻结规格确有笔误，且必须在最终消息说明）
- 新建：.omo/evidence/task-5-phase0-mvp.md
- 禁止：git add/commit/stash；改动其他任何文件；跑全量测试套件

## 验证命令（全部路径级 scoped）

```bash
uv run pytest tests/geom/ tests/test_layering.py -q          # 预期 128 passed
uv run ruff check src/mycad/geom tests/geom
uv run ruff format --check src/mycad/geom tests/geom
uv run basedpyright src/mycad/geom tests/geom 2>&1 | tail -2  # 预期 0 errors
```

## 篡改探针（红→绿，必做并在 evidence 记录）

修完后：往 `_b123_features.py` 的极角计算里把 `cos`/`sin` 互换（或角度加 π/2）→
`uv run pytest tests/geom/test_features.py -q -k hole_pattern` 必须 FAIL → 还原 → 必须全绿。
记录两条命令输出摘要到 evidence。

## evidence 文件（.omo/evidence/task-5-phase0-mvp.md）

结构仿 .omo/evidence/task-3-phase0-mvp.md（先 cat 它参考格式），包含：
1. 交付组件清单（profiles/kernel diff/_b123_features/test_features）
2. 上述四条验证命令结果
3. 篡改探针红→绿记录
4. 继承说明：前任交付 125/128，本代理修复 3 个 hole_pattern 角度语义失败
5. 风险与遗留

## 结尾必做

最终消息以 DoneClaim JSON 结尾（task/changed_files/tests/manual_qa/cleanup/risks 字段）。
遇范围外阻塞：输出 BLOCKED: <原因> 并停止。
