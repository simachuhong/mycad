# P2-10｜GUI 长任务串行执行与关闭策略

## 决策与实现

基于 [P2-09 参考机基线](task-P2-09-end-to-end-performance.md)，25 个特征开始，文档打开、撤销/重做和冷网格读取超过 200 ms；
100 个特征场景下打开/撤销/重做 P95 约 4.0–4.4 秒。因此将所有 GUI 发起的建模写入统一放入主窗口拥有的
`SerializedExecutionUnit`，没有同步快速分支，也没有隐藏队列。100 特征任务中点历史态（ordinal 49）网格按需冷生成约 386 ms，
因此显式历史树项预览也通过该执行单元生成网格，再将不可变 `ViewportData` 交回 GUI 呈现。

- CLI 行、确认计划批次、打开文档、撤销、重做、显式重建与历史特征网格预览共享一个单线程 worker，每次只接受一个操作，忙碌时拒绝重复提交。
- 文件打开和几何操作在 worker 上预热当前网格。冻结的 `ExecutionResult` 信封通过 Qt 队列回到主线程；payload 不包含 Qt 对象，打开完成时才将 `LoadedDocument` 交给 GUI，后续模型写入继续经过同一 worker。面板、视口、菜单状态与文档绑定只在 GUI 线程更新。
- 文档绑定时增加会话代次；旧文档任务的迟到结果被丢弃，不会重新绑定已切换的文档。
- 忙碌时禁用建模、计划执行/取消和其他操作，CLI 输入禁用并显示“执行中”；“退出”仍可触发关闭尝试，但关闭处理会告知任务未结束并拒绝关闭。
- 执行开始后不支持中断 OCCT。单命令由 Command Bus 完成提交或回滚；计划批次按既有原子批事务整体回滚。owner 被直接销毁时，teardown 会等当前操作自然返回后停止并 join 线程。

QThread 组合测试的根因是生命周期测试直接调用取消的 `closeEvent`，窗口并未真实关闭，测试清理时仍销毁了带运行中子线程的 owner。现已在 owner 销毁信号中加入安全 join，并以活动 worker 在销毁时自然完成的回归用例覆盖；不使用 `QThread.terminate()`。

## 验证

- `uv run pytest tests/scripts/test_benchmark_phase2.py tests/ui/test_execution.py tests/ui/test_open_atomic.py tests/ui/test_plan_confirm.py tests/ui/test_document_lifecycle.py tests/ui/test_viewport.py tests/ui/test_picking.py tests/test_layering.py -q`：57 passed。
- 历史树项预览的网格提取不在 GUI 线程运行；测试覆盖 worker 提交、主线程应用快照与重复请求拒绝。
- `uv run ruff check`（本任务 14 个 Python 路径）：通过；`uv run ruff format --check`：14 个文件已格式化。
- `uv run basedpyright`（基准、执行单元及 GUI 接入路径）：0 errors, 0 warnings, 0 notes；`git diff --check`：通过。
- MainWindow 忙碌关闭、空闲关闭、CLI 建模/打开/撤销、历史预览工作线程，以及计划重复提交和旧会话丢弃均有专项测试。
- 显式视口重建先在线程中预热网格，完成后再由 UI 线程刷新场景；历史树点击测试等待异步预览完成。
- 执行中关闭请求只拒绝关闭，任务完成后用户再次关闭；不取消任务。失败时由 Bus 提交/回滚语义处理。强制终止 OCCT 线程不属于允许策略。
