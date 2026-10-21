# 任务证据：todo 10 拾取+结构树双向高亮（phase1-desktop-shell）

提交：`feat(ui): color-coded picking with tree<->viewport bidirectional highlight`
日期：2026-10-21　范围：viewport 拾取/高亮 + right_panel 选中联动 + main_window 接线 + tests/ui/test_picking.py（7 案例）

## KEY DESIGN DECISION：数学拾取而非 GL 读回

计划为 glReadPixels 颜色编码拾取预授权了回退：离屏（CI/offscreen）GL 读回不稳定时
降到「数学射线 × 三角形求交」。实施评审后**直接采用回退路线**并记录于此：
- offscreen/CI 无渲染管线依赖，picking 完全确定可复测；
- 每快照 Tessellation 用 Möller–Trumbore（不裁背面、只取 t>eps 正向），
  全历史快照求交取最近 t（镜像深度缓冲语义）；并列 t 遵循「历史序先到先得」。
- feature_id→ordinal 映射按快照位置 zip（快照序 == Document.commands 序；
  尺寸不一致时映射为空，不映射错误 ordinal）。

## 高亮实现

选中快照网格以半透明琥珀色 GLMeshItem 叠加（`HIGHLIGHT_COLOR=(1.0,0.62,0.10,0.45)`）：
highlight_feature(ord) 加 overlay、highlight_feature(None) 移除；feature 已消失时自动清理。
破坏性命令（boolean_cut）高亮即**终结后状态**（后执行快照）。

## 双向联动

- 树→视口：用户点击（itemClicked）→ `structure_selection_changed(ord)`
  → `_on_structure_pick` → `viewport.highlight_feature(ord)`
- 视口→树：`feature_picked(ord)` → `_on_viewport_pick` → `right_panel.select_feature_ordinal(ord)`
  （编程式选中**不再**回发 selection 信号——无回环；这是有意设计）
- 编程式清除：clearSelection + `setCurrentIndex(QModelIndex())` 复位 currentItem
  （PySide stub 把 setCurrentItem(None) 定型为非 None，类型安全等效替代）

## 测试矩阵（tests/ui/test_picking.py，7 案例 · 188-case scoped lane 全绿)

1. 快照 id 按命令序（feature.box:0 / feature.cylinder:1；feature_ordinal 未知 → -1）
2. 前置快照命中：(0,0)→cylinder:1；(35,0)→box:0；(500,500)→None（空点不选中）
3. 高亮往返：highlight_feature(1) → overlay 计数 2→3→2（公共可观察面 `view.items`）
4. boolean_cut 后语义：ids == [feature.box:0, modify.boolean_cut:1]，
   (0,0) 与 (35,0) 均 → feature.box:0（并列先到先得规则）
5. 无相机 pick_at → -1（相机 'pos' 未初始化守卫：`if "pos" not in self.opts: return None`）
6. 视口发 pick 信号 → 树叶选中（data(0, ORDINAL_ROLE) == 1）→ emit(-1) 清除标志物
7. 树点击（itemClicked.emit）→ 视口 highlight_ordinal() == 1

## 关键缺陷根因（记录供复用）

**offscreen 关窗挂死**：脏文档窗口走 `closeEvent → _confirm_unsaved_changes →
_ask_save_dialog`，真实 QFileDialog exec() 在 offscreen 阻塞——faulthandler/gdb
排查实证。与 todo 8 同一根因：tests 需要 autouse `_ask_save_dialog → "discard"`
补丁（test_picking.py 已加，与 test_document_lifecycle.py 同型）。

零类型抑制：ruff / ruff format / basedpyright（1.40.1 strict）三文件全 0。
