# U02 公共动作与环境布局 Implementation Plan

> **For agentic workers:** 在当前会话按 superpowers:executing-plans 逐项实现，遵守项目 scoped 验证与现有未提交改动保护。

**Goal:** 为共用动作建立身份目录，并按环境隔离有版本的布局设置，不让文档或草稿在切换中串用。

**Architecture:** UI 层 `ActionCatalog` 持有现有 `QAction` 的引用而非复制状态，`WorkspaceLayoutStore` 使用 QSettings 保存独立环境布局及一次性旧值备份。主窗口在文档环境切换时显式保存/恢复相应布局；零件内草图单独归属其零件，独立二维现有内部工具栏状态继续保留。

**Tech Stack:** Python、PySide6 `QAction`/`QSettings`/`QByteArray`、pytest-qt。

**Spec:** `docs/design/2026-11-04-unified-ui-design.md` §§4、8–9；`docs/design/2026-11-04-unified-ui-todo.md` U02。

## Global Constraints

- U00 ST10/AutoCAD 参考核对及 U01 真实 GPU 人工验收未完成；自动化工程验证不代替它们。
- 动作与原菜单、工具栏复用同一 QAction，保留插件与现有命令处理，不复制建模数据。
- 环境为 `home`、`drawing2d`、`part`、`part-sketch`、`drawing`、`assembly`；装配仍不可创建。
- 旧值必须先备份、只迁移已有适用环境；重置当前环境不删除其他环境值、文档或二维内部状态。
- 不改存档 schema、几何内核、Command Bus 或已确认的来源身份契约。

## Review Focus

- 含旧布局但无新版本：备份原始值且仅迁到其对应环境；重启幂等。
- 新旧设置并存或新版本不支持：不覆盖已存在的新设置，不破坏旧值。
- 用户输入框获得焦点：绘图快捷键不吞普通文字或数字。
- 文档切换/修订变化：旧候选不可提交，草稿、视图仍归原文档。
- 调整或重置某工作台：其他环境布局和独立二维工具栏状态保持。

## Task 1 — 动作身份目录

**Files:** 新建 `src/mycad/ui/action_catalog.py`、`tests/ui/test_action_catalog.py`。

**Interfaces:** `ActionCatalog.register(action_id: str, action: QAction) -> None`；`ActionCatalog.get(action_id: str) -> QAction`；重复注册同一 ID 且对象不同时抛 `ValueError`，重复同一对象幂等，未知 ID 抛 `KeyError`。

- [x] 测试相同对象在两个入口启用及选中状态一致，冲突不会替换原动作；先观察测试失败。
- [x] 实现目录并复跑 scoped 测试、ruff 和 basedpyright。
- [x] 把文件、撤销/重做、三维建模和草图入口已有动作登记至目录；菜单及工具栏继续复用同一 QAction，验证现有行为。

## Task 2 — 环境布局存储与迁移

**Files:** 新建 `src/mycad/ui/workspace_layout.py`、`tests/ui/test_workspace_layout.py`。

**Interfaces:** `WorkspaceLayoutStore(settings: QSettings)`；`load(environment: str) -> QByteArray | None`，`save(environment: str, state: QByteArray) -> None`，`reset(environment: str) -> None`，`migrate_legacy() -> None`。键使用 `workspace-layout/v1/<environment>`；首次迁移将已有 `mainWindow/state` 原值备份至 `workspace-layout/legacy/mainWindow-state`，仅在 `part` 新键缺失且旧值是 QByteArray 时复制；保留 `layout/draftingToolbars` 和全部旧键。

- [x] 测试单环境往返、重启、互不覆盖、只重置当前环境、旧值备份、重复迁移及已有 part 状态优先；先观察失败。
- [x] 实现存储并验证 malformed 旧值与未知环境的安全行为；不得清除旧配置。
- [ ] 将环境状态与主窗口实际切换、重启和当前环境重置相连；先编写使用真实窗口及二维/三维往返的测试，确认无草稿或视图丢失。

## Task 3 — 焦点与活动命令隔离

- [ ] 逐项核查二维绘图快捷键、文本焦点、跨文档候选和 Ribbon 页切换行为；先在对应 UI 测试中复现具体缺口。
- [ ] 仅修复测试证实的缺口，复跑 `tests/ui/test_workspace_tabs.py`、`tests/ui/test_menus_toolbar.py`、`tests/ui/test_legacy_layout_startup.py` 和相关命令测试。
- [ ] 保存布局迁移与真实窗口证据；未执行真实 GPU、输入法或用户验收的项保持待复验。
