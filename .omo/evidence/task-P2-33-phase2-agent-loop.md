# P2-33 — 草图约束求解与设计意图反馈

日期：2026-10-25。状态：**partial，仍在开发**；不代表 P2-33 完成或 Solid Edge 人工验收通过。

## 本轮交付

- core 新增后端无关的约束/几何引用 DTO，覆盖重合、水平/竖直、平行/垂直、相切、同心、相等、固定、长度、距离、角度、半径和直径；保留稳定 constraint/entity UUID、驱动/参考语义、来源与单位。
- geom 通过 PlaneGCS 0.9.6 实现可丢弃预览，原草图不被原地修改。成功结果返回自由度、冗余/冲突 ID 和可供 Bus 确认的持久参数；失败不返回部分几何。固定点锚定、矩形边连接/正交和弧线有向扫角作为求解几何不变量处理。
- `sketch.constraint.add@1` 经 ADR-003 释放，参数包括草图基础状态 SHA-256、constraint DTO、solver id/version、DOF 和稳定实体身份的求解坐标。BuildKernel 校验预览仍对应当前状态、几何身份/类型/构造属性不变，随后重放已记录坐标，不重新求解。
- UI 新增“特征 → 草图约束”对话框：按草图、图元和子引用选关系，支持预览/取消/显式确认；确认异步经 Bus 提交。失败与不可用状态可见；参考尺寸只读测量，不改变几何。
- v2 新保存包含可选 `planegcs` 依赖 provenance；旧 v2 文件仍可在缺少该字段时读取。`sketch-constraints` extra 只在 x86-64 marker 下安装，aarch64 dry-run 未安装 Planegcs。

## 验证证据

- scoped 回归：`uv run pytest tests/geom/test_sketch_constraints.py tests/geom/test_sketch_commands.py tests/core/test_sketch_constraints.py tests/core/test_schema_v2.py tests/core/test_persistence.py tests/builtin_commands/test_specs.py tests/ui/test_sketch_editor.py tests/ui/test_sketch_constraint_dialog.py tests/test_scope_audit.py tests/test_layering.py tests/test_adr_docs.py tests/test_notice.py -q` → **177 passed**。
- `uv run ruff check` 覆盖本任务触碰的 core/geom/ui/spec/test 文件 → 通过。
- `uv run ruff format --check` 覆盖相同文件集 → 通过。`basedpyright` 覆盖实现和相应测试 → 0 errors / 0 warnings / 0 notes。
- `uv lock --check` → 通过。`uv sync --dry-run --frozen --python-platform manylinux_2_39_aarch64 --extra desktop --extra sketch-constraints` → 没有计划安装 Planegcs；未执行目标平台真实构建。
- x86-64/CPython 3.12 的尺寸残差校准：0.01、1、1000、100000 mm 线段长度样本通过 `max(1e-12 mm, sketch_extent × 1e-9)` 检查；角度阈值 `1e-7°`。1000000 mm 样本返回失败且无部分结果。小幅尺寸扰动保留已固定端点的正向解分支；反向初始种子仍可能收敛到不同分支，符合 ADR-010 的显式 seed 限制。
- 冲突样本：同一条线水平后再竖直会退化为零长度；MyCAD 拒绝结果并列出相交引用的已有约束与新约束 ID。重复水平关系能报告冗余 ID。

## 2026-10-25 后续：独立关系残差校验

- PlaneGCS 返回成功后，geom 适配层现在额外测量驱动几何关系：点/线性关系阈值为 max(1e-7 mm, sketch_extent × 1e-9)，方向关系阈值为 1e-7°；失败时返回冲突约束 ID，且不返回候选草图。固定点按原始已接受草图坐标比较。
- 残差覆盖固定、重合、水平/竖直、平行/垂直、同心、线/曲线相等、线-圆弧/圆-圆弧/弧-弧相切。弧相切还核验接触点处于有向扫角内，避免把支撑圆上但弧段外的接触误认作有效。
- 负向回归通过伪造求解器读回的非水平结果，确认 PlaneGCS 的 success 不会越过 MyCAD 校验；另有扫角外相切拒绝案例。水平关系在 0.01、1、1000、100000 mm 四个尺度的 x86-64 求解样本均通过。适配器测试现为 30 passed；扩展关联回归集（含右侧结构树、绘图捕捉与范围审计）203 passed。Ruff、格式、basedpyright 对本次变更文件通过。
- 结构树命令归组将命令 ID 按首段判断，避免范围审计把 sketch. 前缀误判为尚未释放的新命令 ID；tests/test_scope_audit.py 与 tests/ui/test_right_tabs.py 合计 33 passed。

## 尚未完成 / 人工验收

- 尚无自动推断约束；没有鼠标拖动几何时实时重求解、约束图标/实体高亮、已保存草图的元素编辑或尺寸变更后的下游特征更新。当前引用通过对话框列表和短 UUID 选择。
- 求解器未在 aarch64/T2 构建验证；普通二维草图可用性不依赖求解器。
- 尚未完成独立二维文档类型、关联模型面的草图、修剪/偏移/图层/DXF，以及闭合草图直接拉伸/旋转/孔的完整工作流。这些仍属于 P2-32、34、35、36，不能用本任务的草图 Bus 回放通过代替。
- 真实桌面鼠标体验、设计意图和 Solid Edge 固定版本逐项对照留给用户明日人工测试；本轮没有宣称 Solid Edge 等同或通过人工验收。

## 2026-10-25 后续开发：基础自动水平/竖直推断

- 草图编辑器新增默认开启且可关闭的“自动关系”。直线端点接近水平或竖直方向（5° angular tolerance）时，预览/精确坐标输入会将其对齐到准确轴向，并在草图中持久化 `source="inferred"` 的关系约束；短于 8 屏幕像素的线段不自动推断。正交输入仍可独立启用。
- 推断关系随草图 `sketch.create@3` 进入 Bus，核验其引用必须是直线且几何残差在容差内，不调用可选求解器。历史版本 schema 不变。撤销恢复几何与约束；草稿旋转/修剪若破坏关系则移除并在状态栏告知。
- 新增 UI/geom/schema 回归：观察到近水平推断和重放测试在实现前失败；同一实体旋转 45° 的关系失效提示用例也先失败后通过。
- scoped 验证：草图编辑器与约束 UI 51 passed；草图创建和约束 geom 41 passed；核心 DTO/spec 77 passed；scope/ADR/layering/spec 补充集合 101 passed；Ruff/format 通过，basedpyright 0 errors / 0 warnings / 0 notes。
- 仍 partial：自动推断当前只覆盖直线水平/竖直，没有端点重合等完整 IntelliSketch 关系提示；直接拖动求解、约束手柄、跨平台 PlaneGCS 构建与 Solid Edge 实机对照仍未闭合。

## 2026-10-25 当前开发续记（未验证）

- 新草图中唯一端点/顶点/圆心捕捉会持久化重合关系，PlaneGCS 拖柄预览同时保留已满足关系。开放多段线每个顶点都有显式索引引用，完成多段线时也计算唯一重合关系。
- 草稿画布新增基础关系符号：水平 H、竖直 V、重合 ◎；用户约束关系有相应短符号及单位/精度化尺寸文字。符号位置按草图坐标跟随几何，附近标记会错开绘制。
- 当前仍未实现多种自动关系推断、完整 IntelliSketch 提示、专用约束手柄、分支唯一性保证、aarch64 构建或人工 Solid Edge 对照。
- 本续记源代码尚未定向验证；自动检查和桌面验收待 P2 G 开发收敛后进行。

## 2026-10-25 收敛验证更新

上面的“尚未定向验证”是实现当时记录。收敛后的全仓回归覆盖当前约束编辑器、几何约束适配、重放和图标/符号渲染：`uv run pytest -x -q -o faulthandler_timeout=90` → **1518 passed in 308.19s**；Ruff、全树格式检查、basedpyright（0 errors / 0 warnings / 0 notes）及 `git diff --check` 通过。PlaneGCS 的 aarch64 构建、更多自动推断/完整 IntelliSketch 提示和人工 Solid Edge 对照仍未完成。
