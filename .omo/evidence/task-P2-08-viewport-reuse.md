# P2-08｜复用视口场景、选择和高亮数据

## 结果

- 当前模型拾取继续只检查当前快照；选择与取消只切换一个可复用的高亮 `GLMeshItem`，不再反复创建/销毁场景项，也不请求历史网格。
- 主体与高亮共享同一个 `MeshData`。`edit_and_replay` 参数修改会把新网格同步到主体和既有高亮对象，并清除过期选择；空场景会移除所有场景项。
- 关闭视口时停止待处理刷新并释放场景项、网格和文档引用；重绑文档会隐藏既有高亮并使用新文档的当前几何。
- 视口仅订阅 `post_command`、`geometry_rebuilt`、`command_amended`。元数据和命名组变化不改变视口数据，因此不会重建场景或清除有效选择/历史预览；面板继续由主窗口自己的信号订阅刷新。
- 着色/线框仍通过场景项可见性切换，保留主体/边线对象；拟合相机和事件合并刷新路径未改变。没有引入空间索引。

## 验证

- `uv run pytest tests/ui/test_picking.py tests/ui/test_viewport.py tests/app/test_open_atomic.py tests/test_layering.py -q`：36 passed。
- `uv run ruff check src/mycad/ui/viewport.py tests/ui/test_picking.py tests/ui/test_viewport.py`：通过。
- `uv run ruff format --check src/mycad/ui/viewport.py tests/ui/test_picking.py tests/ui/test_viewport.py`：3 files already formatted。
- `uv run basedpyright src/mycad/ui/viewport.py`：0 errors、0 warnings、0 notes。
- `git diff --check`：通过。
- TDD 红绿：选择/取消对象复用、参数编辑后高亮数据同步、dispose 清理，以及注释变化不刷新视口的用例均先对旧行为失败，再在对应修正后通过。
- 独立代码审阅未发现 Critical/Important 问题。审阅提出的注释信号无须重建视口问题已修复，并同步更新模块说明。
