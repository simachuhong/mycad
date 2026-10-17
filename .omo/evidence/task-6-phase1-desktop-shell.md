# Todo 6 证据 — 左栏注册表驱动命令库 + PlanDraftController

- 分支 phase1-desktop-shell；执行会话 Sisyphus（ultrawork）。
- 闸门：`QT_QPA_PLATFORM=offscreen pytest tests/ui tests/test_layering.py
  tests/test_scope_audit.py tests/core/test_signals.py -q` → **55 passed**；
  `basedpyright src/mycad/ui` → 0 errors 0 warnings 0 notes；
  `ruff check`/`ruff format --check` src/mycad/ui + tests/ui 全过。
- 探针（红绿闭环）：`_zh_label_of` 篡改为恒 `""` →
  `test_search_matches_id_and_zh_label` **FAILED**（「孔」搜索 0 命中）→
  还原 → **passed**。zh-label 路径真实受测。

## 交付物
1. `src/mycad/ui/plan_draft.py` — PlanDraftController(QObject)：
   持有 core.plan.Plan + selected_step_index；API steps()/params_of(step)/
   select_step(i)/replace_plan(plan)/new_draft(command_id)/set_params(step,
   params)；Qt 信号 params_changed(int, dict)（携带步序号+验证后参数）/
   plan_replaced()。合同与 todo 7 右栏「选项」、todo 12 底栏确认卡共享。
2. `src/mycad/ui/command_palette.py` — CommandPalette(QWidget)：
   QLineEdit 搜索（id 与 label_zh 中文双向匹配；registry.search 有意排除
   中文，故 UI 侧自过滤——实测「hole」与「孔」都命中 feature.hole +
   feature.hole_pattern）+ QTreeWidget 按 id 首段分组（list_by_category，
   feature/modify 两类、八条 P0 全量）+ 底部逐字提示「插件命令自动出现」
   + `refresh()`（§5.3 承诺：后注册命令可见）。§5.3 `register_left_item`
   预留 API 以模块 docstring 落契约注释（计划原文要求）。
3. `src/mycad/ui/main_window.py` — services 非空时左栏 dock 挂载
   palette（标题「命令库」）并新建 PlanDraftController；
   `command_activated` → new_draft 起草单人单步草稿，
   status_command 显示「草稿：<id>」；不可规划命令（插件 demo.*）捕获
   ValueError 显示原因（无空 catch）。

## 实测修正（诚实记录）
- **PlannedCommand 是 frozen dataclass**：set_params 不能直改 step.params
  → 设计为「验证通过后以 dataclasses.replace 替换 steps 列表中的该步」，
  返回验证后（补默认值）参数 dict。`params_of(step)` 仍可读；
  params 变更必然伴随新 step 对象（消费方经 steps()/params_changed 重取）。
- **MainWindow 属性不可叫 palette**：与 QWidget.palette() 方法
  （返回 QPalette）构成 reportIncompatibleMethodOverride →
  改名 `command_palette`。
- `new_draft` 对未注册 id 抛 UnknownCommandError（registry.get 先行），
  对已注册但不可规划（无 AFFECTED_OBJECTS 条目）抛 ValueError——
  计划文档区分两者，测试分别覆盖。
- AffectedObject 是八个语义对象字面量（box_body 等，非命令 id）；
  PlanDraftController 经 AFFECTED_OBJECTS 映射 + cast 构建（validation.py
  已有同类 cast 先例；项目零 type:ignore 规则不受影响）。
- 插件同源测试用可调用 discoverer（`build_app(discoverers=[...])` 直连
  register_plugins），走真实发现→装载→注册链路；另测 `refresh()`
  捡起构造后注册的 spec（§5.3 语义）。

## 范围纪律
- 未新增命令 id；未做拖拽；无灰态 P1/P2；标签格樗「中文（id）」。
- core/ 零改动；几何层零改动。
