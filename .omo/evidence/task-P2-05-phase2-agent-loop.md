# P2-05 — 当前模型拾取与历史预览

日期：2026-10-24；分支 `codex/phase2-foundation`；本批为工作区改动。

## 改动与行为

- `ViewportData.state_id` 现在明确标识命令执行后的完整模型状态，不再把历史状态误称为可拾取实体的 `feature_id`。协议说明该 ID 不提供面、边、实体到来源特征的映射。
- 默认射线只测试当前快照。命中会选中当前模型整体并显示选择叠层，不会把命中位置映射到任一命令 ordinal；空射线、通孔和已被 `new` 替换的旧几何均无命中。
- 用户点击结构树特征行时，视口进入显式历史预览，以该命令执行后的完整状态替换场景，不把旧网格叠在当前模型上。状态栏显示预览 ordinal；“视图 → 返回当前模型”及工具栏同名操作退出预览。预览期间禁用当前模型拾取；模型刷新会清除过期预览与当前选择。
- 空结果仍是默认当前状态；只有明确选择历史行才会显示旧快照。同步更新阶段 2 UI 方案、UI 初稿及 P2-04 行为说明。

## 验证

- 修复前定向拾取用例复现 E04：穿过通孔的射线返回 `feature.box:0`，替换掉的盒子仍可在 `x=35` 命中；新增 API 用例按预期失败。
- 修复后运行：
  - `uv run pytest tests/core/test_viewport_protocol.py tests/geom/test_viewport_snapshots.py tests/ui/test_picking.py tests/ui/test_viewport.py tests/ui/test_menus_toolbar.py -q`：43 passed。
  - scoped Ruff check 与 format check：通过。
  - scoped basedpyright：0 errors / 0 warnings / 0 notes。
  - `git diff --check`：通过。
  - `uv run mycad gui` 已启动并保持运行，未见启动错误输出；本项没有据此宣称完成真实 GPU 画面验收。

## 限制

当前选中粒度为整个模型结果；本任务没有提供稳定拓扑身份、单独面/边/多个实体选择或来源追踪。测试使用 Qt offscreen 环境，不代表真实 GPU 渲染验收。
