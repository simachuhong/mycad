# todo 2 — core ViewportData 依赖倒置协议

计划：`.omo/plans/phase1-desktop-shell.md` todo 2（GAP-4 core 半）。

## 变更清单

| 文件 | 变更 |
|---|---|
| `src/mycad/core/viewport_protocol.py` | 新文件：`ViewportData` frozen dataclass（feature_id + mesh: Tessellation 复用 + 可选 normals 默认空元组）+ `ViewportPort` runtime_checkable Protocol（`viewport_data() -> tuple[ViewportData, ...]`） |
| `src/mycad/core/__init__.py` | 导出 `ViewportData`/`ViewportPort`（导出序注释同步更新） |
| `tests/core/test_viewport_protocol.py` | 新文件：三契约测试 |

## 设计决议

- **顶点/索引字段零重定义**：mesh 直接复用 `geometry_types.Tessellation`（单一定义点；索引校验在其 `__post_init__`，红路测试用越界索引构造断言 ValueError 即验证继承链）。
- **协议面最小**：线框边由渲染侧从三角形边去重派生；颜色/光照渲染语义不进 core（模块 docstring 明示）。
- 层叠定位：第三依赖倒置（kernel_protocol 之后 ports 之后），核心不引 geom/Qt/numpy——basedpyright 与 layering/scoped audit 双证。

## 测试与中途纠错记录

1. 初版测试调用 `ViewportPort.viewport_data(fake)` 意图直验空元组语义 → 1 failed（Protocol 桩方法体为 `...` 返回 None）。修正为只对 fake 实例断言 isinstance + `port.viewport_data() == ()`。
2. 初版 frozen 断言用了 `# type: ignore[misc]` → **违规即撤**，改为仓库既有惯例（`tests/core/test_geometry_types.py:27-31`）的动态 `setattr`，随附同源出处注释。

## 验收门（实测）

```
uv run pytest tests/core/test_viewport_protocol.py -q   → 3 passed
uv run basedpyright src/mycad/core                      → 0 errors, 0 warnings, 0 notes
uv run pytest tests/test_layering.py tests/test_scope_audit.py -q → 27 passed
uv run ruff check <三文件>                              → All checks passed!
uv run ruff format --check <两新文件>                   → ok
```

红线自查：无 Qt/numpy/build123d import；未触碰既有 Kernel 协议 reset/apply；无新 type:ignore（好险——一处即撤出）。
