# P2 G 最终集成质量记录

2026-10-25，共享 checkout `codex/phase2-foundation`，基准 HEAD `9ab55ac267ffb6ef19fa45321b027048ef7782b2`，未提交的既有改动均保留。此记录为本轮最新代码质量证据；先前1518项历史记录不用于宣称当前完成。

## 一次全量检查

| 命令 | 结果 |
| --- | --- |
| `uv run ruff check .` | All checks passed，exit0 |
| `uv run ruff format --check .` | 316 files already formatted，exit0 |
| `uv run basedpyright` | 0 errors / 0 warnings / 0 notes，exit0 |
| `QT_QPA_PLATFORM=offscreen uv run pytest -q -o faulthandler_timeout=90` | 1678 passed / 2 failed in 483.76s，exit1；两项随后修复，见下 |

## 两项全量失败与收敛

1. `tests/formats/test_guards.py::test_formats_tests_no_app_symbols`：DXF输出预览夹具使用组合根构建完整文档，违反formats测试边界。改为其他格式测试已使用的 BuildKernel 夹具；继续断言真实尺寸SVG、准确字节写入、图层显示/损失报告和导出不改变几何。分层守卫保持原样。
2. `tests/geom/test_kernel_primitives.py::test_apply_rejects_non_mapping_params`：新增重建操作日志在参数检查前调用dict，非法列表抛出ValueError而非原契约ValidationError。把现有checked_mapping移至记录前；正确参数与后续操作重建语义不变。

按项目“全量一次、后续增量”的纪律，修复后复跑受影响范围，未重复整套测试：

```text
uv run pytest tests/formats tests/geom/test_kernel_primitives.py \
  tests/geom/test_sketch_constraints.py tests/geom/test_body_provenance.py \
  tests/test_layering.py -q
160 passed in 26.31s, exit0
```

两个变更文件（kernel.py、test_dxf_output_preview.py）的 Ruff、format 和 basedpyright 复查均通过。此前最终独立审查的5项 Important 已全部红绿修复，并有240项组合回归，见 `task-P2-G-final-review.md` 和 `task-P2-G-final-review-fixes.md`。没有未处置的失败；**不把“全量1678+2失败、修复后定向160通过”改写成一次全量1680全绿**。

## 判定与边界

P2-32～P2-37 原计划工程实现与代理自检完成，可以进入用户人工验收。范围与限制见 `task-P2-G-final-traceability.md`；实际操作顺序见 `task-P2-G-manual-handoff.md`。Windows/aarch64实机、AutoCAD/Solid Edge目标CAD显示、设备交互和性能未由本Linux检查证明，用户验收尚未执行；P2-44及整个Phase2发布验收未关闭。

原始输出保存在本机 `/tmp/mycad-p2g-final-{ruff,format,types,pytest}.log` 及 `/tmp/mycad-p2g-integration-fixes{,-types}.log`。源码没有type/pyright ignore，未重写存档或回退旧命令版本，未提交/推送/清理共享用户改动。

交接桌面：新版XCB GUI正常启动，X11窗口1400×900可见，启动日志为空（`/tmp/mycad-p2g-handoff-gui.log`）。后续提醒经app工具设为PAUSED并读取本地配置确认。
