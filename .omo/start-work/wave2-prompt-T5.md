# T5 geom 特征层 — MyCAD Phase 0 Wave 2（unspecified-high / 机械化执行）

## 第一步（本提示词加载后立即执行，禁止跳过）

```bash
mkdir -p /tmp/opencode/t5
cat > /tmp/opencode/t5/checklist.md <<'EOF'
T5 执行清单（垂直切片，每回合只做一项小动作；文件一律追加式增长）
0. 读 src/mycad/geom/kernel.py 与 src/mycad/core/{selectors,exceptions,geometry_types}.py
1. cat .omo/evidence/spike/flange_spike.py 与 fillet_probe.py（权威习语，禁止改签名）
2. profiles.py：SPDX 头 + Profile 抽象 + CircleProfile（仅 ~40 行）
3. profiles.py：追加 RectProfile + __all__（~25 行）
4. tests/test_features.py：SPDX 头 + imports + test_extrude_circle 两个断言（~30 行）→ pytest 跑（红：AttributeError 即预期失败）
5. kernel.py：feature.extrude（圆+方，~50 行）→ pytest 跑（绿）
6. 追加 test_extrude_rect + test_extrude_negative_distance → 红
7. kernel.py 补 extrude 分支 → 绿
8. 每原语重复此微循环（每次只追加 2-3 个测试或 ~50 行实现）：
   a. revolve：合法轴 2 测试 + 非单位轴/(0,0,0) 2 错误测试 → 实现
   b. fillet：体积差测试 + 半径过大错误测试 → 实现（方法式 part.fillet(radius, edge_list)）
   c. boolean_cut：box 切圆柱解析体积测试 → 实现
   d. hole：through_all 体积测试 → 实现；blind 体积测试（π·2²·5）→ 实现；−Z 面 blind 反向测试；圆柱面 target-not-plane 测试；谓词不匹配测试
   e. hole_pattern：孔心坐标断言（+Z/−Z、start_angle 0/90）→ 实现；法兰 golden（体积 36794.3331588437/bbox/圆柱面 6/命令 id 扫描）→ 绿；+X 面 pattern-target-not-horizontal；kind=linear 拒绝
9. QA 内联脚本跑法兰 + 两 failure 用例 → 写 .omo/evidence/task-5-phase0-mvp.md（分段追加）
10. scoped 四门（pytest tests/geom -q / ruff check / ruff format --check / basedpyright）
11. DoneClaim 回传
EOF
cat /tmp/opencode/t5/checklist.md
```

**硬性反停摆纪律（上一执行者死于此，违反即重蹈覆辙）**：
- **单次文件写入硬上限 ~100 行**。任何文件（源码/测试）一律用 `cat >> file <<'EOF'` 追加式增长，**禁止一次写整个大文件**，禁止"先写完整骨架再填充"。
- 每回合 = 恰好一个小动作（一次追加 OR 一次测试运行 OR 一次小修复），动作完成立即结束回合。
- 禁止在回合内展开长篇设计推理——设计已在本任务书中写死，你只做机械转写。
- 测试文件长就拆成多次追加：2-3 个测试函数一批。

## 上下文

- 项目：MyCAD Phase 0 headless 可编程 CAD（build123d 0.11.1 封层）。仓库 /media/sima/Data/projects/MyCAD，一切命令经 `uv run`。
- T1 已交付：`src/mycad/core/exceptions.py`（15 类异常，闭合清单，**不新增异常类**）、`geometry_types.py`（MassProperties/BoundingBox/Tessellation 中立 DTO）、`selectors.py`（FaceSelector/EdgeSelector 谓词，六规则：面积降序+面心字典序平局、圆柱轴无向、plane 必填 axis）。
- T2 已交付：`src/mycad/geom/kernel.py`（BuildKernel：reset/apply(box+cylinder 三模式 new/add/cut)/mass_properties/tessellate，GeomVersionError 版本门）+ `tests/geom/` 现有测试（风格参照）。
- 你在 T2 地基上扩展特征层。**先读现有代码，习语与类型风格照抄**。

## 范围白名单（只允许创建/修改）

- `src/mycad/geom/profiles.py`（新建）
- `src/mycad/geom/kernel.py`（扩展 apply；可新增同包私有模块如 `_b123_ops.py`）
- `tests/geom/test_features.py`（新建）
- `.omo/evidence/task-5-phase0-mvp.md`（最后写证据）
- **只读**：src/mycad/core/**、src/mycad/commands/**、tests/commands/**、tests/core/**、docs/**；禁改 tests/test_layering.py（geom 内拆模块不触发守卫——守卫只判"geom 包外不得 import build123d/OCP/numpy"；若意外失败→报告而非改守卫）。

## 规格细节（逐字来自计划 phase0-mvp.md T5 节，零发明权）

### profiles.py
- frozen dataclass，标准库类型：`Profile` 抽象 + `CircleProfile(radius, center=(x,y))`、`RectProfile(width, height, center=(x,y))`（阶段 0 只这两种）。
- 截面位于工作平面（默认 XY，z=0；绕 X/Y 旋转的 datum 平面描述**仅留字段不实现**）。

### kernel.apply 新命令
- **feature.extrude**：profile + distance 双向符号 + mode new/add/cut。
- **feature.revolve**：profile + axis 枚举 X/Y 或过原点方向向量 + angle_deg（默认 360）。
  - **轴归一化（写死）**：axis 为三元组时 geom 层构造前断言 `abs(norm(v)-1.0) <= 1e-9`，超差抛 `ValidationError`（消息含原始向量与实测 norm；**不自动归一化、不 warning**）；方向向量取反合法；测试：(1,0,0)/(0,1,0) 合法、(1,1,0) 与 (0,0,0) 必须 ValidationError。
- **feature.hole**（以几何谓词定位）：`target_face: FaceSelector` + position 描述子（`{"kind":"center"}` 面心，阶段 0 只支持 center，其余 schema 拒绝非静默，不允许裸拓扑索引）+ diameter + depth（`{"kind":"through_all"}` 或 `{"kind":"blind","value":...}`）。
  - target_face 必须解析为**平面**：非平面（如圆柱面）固定抛 `TopologyReferenceError(reason="target-not-plane", descriptor 回显)`。
  - **钻孔方向（写死）**：孔轴=定位面在面心处的**外法向**；blind 沿外法向反方向（向材料内部）延伸 value；through_all 沿该轴双向包围盒穿透整个实体（build123d 以该面外法向为轴的贯通孔，尖刺法兰路径已实证）。
- **feature.hole_pattern**：base_hole 经 `{"$ref": "#/$defs/Hole"}` 共享 Hole 定义（含自己的 target_face 谓词）+ pattern `{"kind":"polar","radius","count","start_angle_deg"}`（只实现 polar；kind=linear 由校验层明确拒绝，非静默）。
  - **极阵列局部坐标系（#round7-3，"阶段 0 限制"方案，零发明权）**：阶段 0 仅接受 base_hole.target_face.surface=="plane" 且 axis 为 "+Z"/"-Z" 的水平面——①schema 层不拒（+X 等平面对 feature.hole 仍合法），geom 执行 hole_pattern 时校验解析平面外法向与全局 Z 平行（|n·ẑ| ≥ 1−1e-9），不满足固定抛 `TopologyReferenceError(reason="pattern-target-not-horizontal", descriptor_json=...)`；②角度参考系=全局 XY：第 i 孔心相对基面面心位于 `(R·cos(θ0+2πi/count), R·sin(...))`，start_angle_deg=0 ⇔ 全局 +X，正向从 +X 朝 +Y（自 +Z 俯视逆时针），−Z 面不镜像；③每实例孔方向跟随该定位面外法向；④一般斜面投影局部系是阶段 1 演进口，不实现。
  - 测试：+Z/−Z 面各一例孔心坐标解析断言；+X 竖直面 base_hole 执行 hole_pattern→pattern-target-not-horizontal；start_angle_deg=90 首孔落 +Y；count=4 孔心集合与法兰 golden 一致。
- **modify.fillet**：edges: EdgeSelector 数组 + radius。
  - **签名已实测锁定（零探索）**：方法式 `part.fillet(radius: float, edge_list: Iterable[Edge])`——**半径在前**；`part.fillet(edges, radius)` 抛 TypeError，禁止使用。边集合=EdgeSelector 解析后的 build123d Edge 可迭代对象；习语 `part.edges().filter_by(GeomType.CIRCLE)`（法兰形返回 4 圆边、e.radius∈{10.0,40.0}）。半径过大 OCCT 报错→包装 GeometryBuildError。geom 内**固定只用方法式**。
- **modify.boolean_cut**：tool 内联原型体 {type:box|cylinder,...}，唯一使用 cut 动词的命令。

### 法兰语义约束（验收牵引）
- 法兰中心孔与 4 均布孔**必须**走 feature.hole / feature.hole_pattern 谓词路径（中心孔 target_face=最大 +Z 平面、position=center、through_all）。
- boolean_cut 不是法兰路径，只为通用差集存在，测试用 box 工具体。

### 实现纪律
- 所有 OCCT 交互在 geom 包内；build123d 构造失败（零厚度/干涉/fillet 过大等）统一捕获包装 `GeometryBuildError(command_id, reason, occt_summary)`（带摘要字符串，**禁止 OCP 异常文本穿透边界**）；**不新增异常类**。
- 复用尖刺习语：PolarLocations + Cylinder(mode=SUBTRACT)（.omo/evidence/spike/flange_spike.py 27-47 行）；fillet/box/cylinder 三模式见 fillet_probe.py 全部实测输出（**引用即权威**）。

### 测试 tests/geom/test_features.py（验收标准逐条）
- extrude 圆截面（体积 πr²h）/方截面；revolve 矩形绕 Y=360 体积解析。
- hole through_all（谓词选最大 +Z 面、center）后体积=原体积−π(d/2)²·贯通长度。
- **尖刺法兰 5 孔全部谓词路径**：cylinder r40 h8 → feature.hole 中心 φ20 through_all → feature.hole_pattern polar 4×φ6@R25，体积 36794.3331588437…（=math.pi*8*(40**2-10**2-4*3**2)，容差 1e-6）、bbox.size=(80,80,8)、圆柱面 6。
- **序列命令 id 扫描断言**：上述序列中不出现 mode=cut 的 cylinder、不出现 modify.boolean_cut。
- fillet 前后体积差与边数变化（Box 10³ 顶边 radius 1.0 实测体积 991.7994 可参照）。
- boolean_cut box 切圆柱解析体积。
- 错误场景：孔定位谓词不匹配（TopologyReferenceError 含命令 id）；fillet 半径>几何允许（GeometryBuildError）；pattern.kind=linear 明确拒绝；revolve 非单位轴 ValidationError；同一几何连续两次 hole 但面已变化→显式异常非静默选错面。
- **盲孔**：Box20³ 顶面 center 打 blind（diameter=4,value=5），唯一验证=mass_properties 体积断言：减少量恰 π·2²·5（贯通则 π·2²·20，禁止 STEP 读回/截面查询第二路径）。
- **盲孔反向语义**：同一实体 −Z 面打同样盲孔，孔仍向材料内部。
- **target_face 选圆柱面**→TopologyReferenceError(reason="target-not-plane")。
- 每条新原语至少 3 测试（解析体积/错误谓词/OCCT 失败包装）。

### Must NOT do
- 不做自由草图/约束求解器（无 sketch.*）；不实现 hole_pattern linear/chamfer/shell/mirror（注册表不出现这些 id）；不引入 numpy DTO；不吞 OCCT 异常；不在 commands 包做几何计算。

## 编排规则（硬性）

1. **路径级验证**（禁裸全量套件）：`uv run pytest tests/geom -q`、`uv run ruff check src/mycad/geom tests/geom`、`uv run ruff format --check src/mycad/geom tests/geom`、`uv run basedpyright src/mycad/geom tests/geom`。
2. **禁 git add/commit/stash**（提交由编排者做）。
3. 新文件 SPDX 两行头（与现有文件一致的 MIT 头，照抄 src/mycad/geom/kernel.py 头部）。
4. basedpyright strict 零逃逸（禁 `# type: ignore`/`typing.cast` 滥用；测试文件同样零告警）。
5. TDD：每原语先写失败测试再实现。
6. 遇范围外阻塞：回复开头写 `BLOCKED: <原因>` 并停止，不自行扩大范围。

## 证据与 QA

- 内联脚本经 kernel.apply 复现尖刺法兰（谓词路径）打印 volume/bbox/圆柱面数 + 两个 failure 用例输出，写入 `.omo/evidence/task-5-phase0-mvp.md`（结构参照 .omo/evidence/task-2-phase0-mvp.md）。

## DoneClaim（结尾逐字回传此 JSON 结构）

```json
{"DoneClaim": {"task": "T5 geom feature layer", "changed_files": ["..."], "tests": ["exact command + result"], "manual_qa": [".omo/evidence/task-5-phase0-mvp.md"], "cleanup": ["..."], "risks": ["..."]}}
```
