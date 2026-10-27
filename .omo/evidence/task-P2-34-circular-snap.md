# P2-34 — 圆与圆弧交点捕捉回归（阶段性证据）

日期：2026-10-25。状态：**partial，测试/验收补充**。本切片没有改变生产捕捉算法；它验证并固定已有候选枚举行为，不能视为 P2-34 或 Solid Edge 人工验收完成。

## 覆盖行为

- 圆弧与圆相交时，只有实际圆弧扫掠范围内的交点作为捕捉候选；新画直线的起点落到该交点。
- 两条圆弧相交时，只有同时位于两条弧有效扫掠范围内的交点可捕捉。
- 现有反例继续确认：底层圆存在交点，但候选角度落在弧的有效扫掠区之外时，不会错误吸附。

测试使用真实草图编辑器和几何输入，并检查最终生成直线的起点坐标；不读取画布私有游标状态。

## 自动验证

```text
uv run pytest tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py tests/test_layering.py tests/test_scope_audit.py tests/test_adr_docs.py -q
117 passed in 51.52s

uv run ruff check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
All checks passed

uv run ruff format --check src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
4 files already formatted

uv run basedpyright src/mycad/core/sketch_edit.py src/mycad/ui/sketch_editor.py tests/core/test_sketch_edit.py tests/ui/test_sketch_editor.py
0 errors, 0 warnings, 0 notes

git diff --check
passed
```

Solid Edge 实机捕捉反馈与误吸附恢复流程待用户验收；尚未运行全仓测试。
