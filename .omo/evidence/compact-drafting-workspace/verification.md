# 二维工作区整合验证

- 最终回归：133 passed in 100.42s。范围：workspace_console、cli_tab、drafting_workbench、driving_dimensions、dim_layers、polygon_grid、drafting_panels、toolbar_workspaces、menus_toolbar、layering。
- 变更路径 Ruff 检查通过，8 个 Python 文件格式检查通过，basedpyright 0 errors / 0 warnings / 0 notes。
- 新功能测试观察到 RED 后实现：移除独立左坞及底部表单、共享可收起控制台、信息日志/瞬时坐标分流、CLI 草稿保护。
- 首次综合回归 131 passed / 1 failed；失败是旧测试仍断言仅 CLI/计划两页。更新为四页并检查真实 CLI/计划实例后，CLI 9 项通过；最终 133 项回归全通过。
- 独立只读复查发现浮动控制台抢占尺寸编辑焦点；新增用例先失败，再修复，覆盖停靠/浮动及标签、CLI/AI/信息/计划菜单共 10 个入口组合，最终回归通过。无遗留复查问题。
- 实际 Qt Fusion 浅色主题截图：workspace.png（图形 Tab + 收起控制台）、drawing-controls.png（绘图参数页）、cli.png、ai.png。1600×960 窗口中，收起控制台高 69 px，展开约 264 px；收起时画布约 1312×573。
- AI 对话页明确显示未连接，允许保留输入草稿，禁用发送；现有代码无 AI 后端，未生成虚构回复或发送网络请求。已询问用户连接范围，未收到连接参数，采用已告知的离线窗口范围。
- 使用 Qt offscreen 验证；没有替换正在运行的 MyCAD，未验证本机窗口管理器下的手动拖拽。
- 当前目录包含大量此前未提交工作；仅修改相关文件，未自动提交或重启应用。实施差异及任务入口快照保留用于复核。
