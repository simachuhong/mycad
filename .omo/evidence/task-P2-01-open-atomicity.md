# P2-01 — 打开文档原子性

日期：2026-10-23。分支：`codex/phase2-foundation`。

## 实现

- `app.open_app_document()` 在组合根创建独立 `BuildKernel`，调用 core 持久化完成候选文档的读取、校验和完整重放。
- 全部成功后才创建活动 `CommandBus`，再通过 `BuildKernel.replace_state_from()` 将已完成的几何状态一次性交给稳定的 `AppServices.kernel`。失败的候选 bus/kernel 未绑定到当前会话。
- GUI 和 CLI 打开都使用同一组合根入口。GUI 将格式/重建/读取错误反馈给用户；失败时不调用会话替换。成功的 CLI 打开只调用一次替换回调。
- 保持 `LoadedDocument`、`.mc.json` v1、Command Bus 写入路径和 core/geom/UI 分层契约不变。

## 验收证据

E01 回归先红后绿。修复前，打开含 `size_x=20` 与后续非法 `size_x=-1` 的存档后，活动模型体积从 `1000 mm³` 变成 `2000 mm³`；修复后旧文档、dirty、路径、undo/redo、视口绑定及 kernel 均保留。失败后另行保存仍写回原文档，STEP 导出仍为原模型体积。

新增场景覆盖畸形 JSON、未知版本、未知命令、后续参数非法，以及候选重放第二条命令时抛出几何错误。GUI 与 CLI 均验证失败后仍可保存、导出和继续重做；成功打开验证替换回调恰好一次，随后 undo 作用于稳定的活动 kernel。

## 本次验证

针对打开与会话边界执行：

```text
uv run pytest tests/app/test_open_atomic.py tests/ui/test_open_atomic.py tests/cli/test_open_atomic.py tests/core/test_persistence.py tests/ui/test_document_lifecycle.py tests/cli/test_builtin.py tests/ui/test_cli_tab.py tests/test_layering.py -q
70 passed in 15.48s
```

改动路径静态检查：`ruff check` 通过；`ruff format --check` 7 个文件已格式化；`basedpyright` 0 errors / 0 warnings / 0 notes；`git diff --check` 通过。未运行全量测试、真实 GPU 桌面验收或远端 CI；本记录只覆盖 P2-01 相关边界，不代表当前工作树整体验收完成。
