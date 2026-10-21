# Evidence — task 7: right dock (structure / properties / options tabs)

- Plan: `.omo/plans/phase1-desktop-shell.md`（todo 7，Wave 2 在线）
- Branch: `phase1-desktop-shell`；断点续作（关机维护中断，ledger 81 行
  `todo7-paused-for-shutdown` 记录了恢复姿态）。

## 交付面

- `src/mycad/ui/right_panel.py`（新建）：`RightPanel(QWidget)` 五固定页
  `RIGHT_TAB_TITLES = ("结构", "属性", "选项", "显示", "测量")`；「显示」「测量」
  占位页 `setTabEnabled(False)`（初稿 §6）。结构树根 = `part_name`/「未命名文档」
  （F-TREE-01，文件 stem 经 `bind_document(document_stem=...)` tooltip），四分组
  基准/草图/特征/实体；特征叶 = `#ordinal 可读名（id）` + UserRole tặng ordinal，
  实体叶 = named_groups 名字；空组「（空）」占位。点击特征叶发
  `structure_selection_changed(ordinal)` 并联动属性表（todo 10 双向联动入口）。
  属性表只读三列（参数/类型/当前值），类型列取 `$ref` 尾段（`Positive`）；
  无选中 → `METADATA_KEYS` 六键文档级只读表（F-PROP-01）。
  选项表绑定 todo 6 `PlanDraftController`（真实控制器编码，非 fake——同源
  决策，见偏差①）；`selected_step_index` 是「编辑哪一步」的唯一答案；
  单元格编辑 → JSON 解析（失败按原字符串）→ `set_params`；`ValidationError`
  → `options_error` 信号 + 单元格回滚（不做空捕获）。
  `register_right_tab` 预留约定 API 注释在模块 docstring（与 register_left_item
  同款，阶段 1 不实现）。
- `src/mycad/ui/main_window.py`：services 分支右栏实例化 +
  `right_dock.setWindowTitle("属性")`；`bind_document` 扩展右栏绑定 +
  `STRUCTURE_REFRESH_SIGNALS`（post_command/geometry_rebuilt/command_amended/
  metadata_changed/named_group_added/named_group_removed）订阅 → 整树刷新
  （计划 References：named_group 信号驱动树刷新）；`document_saved` 刻意不入
  （只动脏标记）。

## 验证

- `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui tests/test_layering.py
  tests/test_scope_audit.py tests/core/test_signals.py -q` = **64 passed**。
- `uv run basedpyright src/mycad/ui tests/ui` = **0 errors / 0 warnings / 0 notes**。
- `uv run ruff check src tests` 全过；`ruff format --check src/mycad/ui tests/ui`
  12 files pass。
- 红绿探针：`RIGHT_TAB_TITLES` 篡改「测量」→「测量X」→ test_right_tabs.py
  **1 failed（测试钉标题序）** → 还原（grep 残留 0）→ **9 passed**。闭环。
- 复门回归：tests/ui 30 passed（含本 todo 9 条 + palette 12 条 + menus 9 条）。

## 测试事实（tests/ui/test_right_tabs.py，9 条）

qapp fixture 必须显式入参（pytest-qt 不自动建 QApplication，无它全进程
Abort）；属性表行键同源 = `services.registry.get(id).params_schema`
properties（5 键：size_x/size_y/size_z/center/mode——命令参数 ≠ 表行键）；
metadata 缺省值 = `""`（source=local）；选项表用 `_explicit_draft`（`set_params`
空字典不填默认，需显式传参）；窗口集成走真实 `loaded.bus.execute`（不伪造
post_command payload）。
遗留债修复：todo 6 `test_command_palette.py` 15 处 basedpyright Optional
窄化（`_all_leaf_ids`/`_leaf_is_hidden`/两组 titles/lambda 捕获）全部
窄化改写，tests/ui 纳入 pyright 检查面。

## 事故与修复（诚实记录）

1. **right_panel.py 曾被补丁脚本用测试侧内容污染覆盖一次**（untracked 无
   git 副本）→ 从会话上下文保存的完整原版重构 348 行成功，全部累积 patch
   均在手。后续 python replace 全部 `assert` 守卫锚点唯一性。
2. **initial pyright cascade 根因**：`CommandRegistry` 误引
   `mycad.plugins.registry`（正确 = `mycad.commands.registry`）；
   `ValidationError` 误引 pydantic（正确 = `mycad.core.exceptions`）；
   `PlannedCommand/Document` 位置（`mycad.core.document`，非 core.plan）。
   JSON-schema 值属无类型 dict → `_properties_of` 统一
   `cast("dict[str, object]", ...)` 收口。

## 语义偏差（决策记录）

① 选项面绑定真实 `PlanDraftController`（计划允许 fake；真实例同源更强，
   PlanDraftController 本就轻量——QObject + registry）。
② docs/文件不涉及；无命令 id 新增；属性表只读达成；测量/草图/基准无真数据。

## 守门对照（计划 Acceptance）

- `uv run pytest tests/ui/test_right_tabs.py -q` 绿 ✓（9 passed）
- scoped 四门绿 ✓（64 passed + 0e + ruff/format）
- offscreen ✓（conftest 已钉 QT_QPA_PLATFORM，pytest 报头无 GUI）
- 红绿探针闭环 ✓（量化：1 failed → 还原 → 9 passed）
