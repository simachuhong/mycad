# Todo 12 证据：计划卡片六态确认（Chat 页 = 计划卡片流）

- 提交：feat(ui): plan-card confirmation pipeline on the six-state plan machine
- 基线：6442c42（todo 10 拾取双链）

## 交付物
1. `src/mycad/ui/plan_cards.py`（新）
   - `_PlanCard(QFrame)`：标题 `命令 <id>（影响: <affected_object>）` + 参数体；
     状态着色 failed=#ffd6d6 / executing|done=#d6f5d6；「编辑」仅 draft 态可点。
   - `PlanCards(QWidget)`：`plan_failed(str)` / `plan_done(int)` 信号；滚动区卡片流
     （末尾 stretch 保留，重建时只删卡不删 stretch）；状态条 + 「取消」「执行」。
   - `bind_draft(draft)` 接同一 PlanDraftController（plan_replaced/params_changed →
     重建卡片）；`bind_document(loaded)` 持有 bus/document。
   - `execute_plan()`：`plan.confirm(actor="gui")` → `bus.execute_batch(plan)` 单调用。
     仅 draft/confirmed 可执行（UI 不可触发非法转移）；BatchRollbackError →
     卡片红（failed_step）+ 已执行步绿 + 状态条含「执行失败/回滚: 盘点 ordinal」，
     ordinal = base(回滚后长度) + i。
   - `cancel_plan()`：仅 draft/confirmed 生效；其余 no-op（done/failed/cancelled
     状态下按钮本已禁用，再按也无害）。
   - `_ParamDialog`：逐键 QLineEdit + OK/Cancel；accept 时经同一 controller
     `set_params` 校验，ValidationError 留在对话框并显示「参数非法」。
2. `src/mycad/ui/main_window.py`：Chat 页由占位 QWidget 换成 PlanCards；
   `bind_draft` 在 bottom dock 建好后接线；`bind_document`/`_replace_document`
   同步 `plan_cards.bind_document(...)`/`bind_draft(...)`。

## 设计决策
- 执行入口严格单调用：confirm + execute_batch 必须同帧，落在「计划级原子」不变量
  上（回滚 = 整批回退，历史长度复原）。
- 六态机的非法转移在两层挡死：按钮 enabled 状态（_update_buttons）+
  execute/cancel 函数内状态守卫。
- 卡片「影响对象」文案直接用 PlannedCommand.affected_object（AFFECTED_OBJECTS
  表，document.py 单源），不做二次翻译。

## 测试（tests/ui/test_plan_confirm.py，5 用例全绿）
- 六态真实序列 draft→confirmed→executing→done（卡文字样、按钮禁用、done 后
  cancel_plan no-op）。
- cancelled 计划 execute_plan 幽灵调用 → no-op 不抛（InvalidPlanTransition 只在
  绕过 UI 时才会出现）。
- 原子回滚场景：2 命令计划第 2 条必败（hole diameter=0）→ BatchRollbackError，
  历史长度复原（== 0）、kernel mass_properties 前后相等、卡片红 + 「回滚: 0」。
- 双命令正常计划 → done，历史恰好 2 条。
- 参数编辑同步：RightPanel Options 表 + 卡片文案由同一 controller 驱动，
  radius 40.0 → 10.0 双面板同步。

## 红绿探针
- 初始 5 用例全红：`PlanCards has no attribute 'plan'`（缺公共只读）→ 补
  `plan` property 后转绿；cancelled-then-execute 用例暴露 confirm 直接抛 →
  补 UI 侧状态守卫（execute_plan 仅 draft/confirmed）后转绿。

## 残余 / 偏差
- `_ParamDialog` 的值解析（json.loads 回退 raw string）沿用 right_panel 的
  行为；numeric 之外的类型（如 bool 开关）以字符串/布尔原始字面量通过校验可行，
  未做表单控件分类（属 todo 12 边界之外的交互打磨）。
- 无多计划并行：一次一张激活卡流（替换式 bind_draft），符合 spec 限制。
- 零类型抑制：3 个落盘文件 basedpyright 0 errors。
