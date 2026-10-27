# 二维人工验收整改

状态：本轮整改及增量工程验证完成；用户复验待执行，四项人工问题未标为验收通过。

## 根因

原实现以独立非模态QDialog+工具下拉框作为绘图入口；画布只有灰色轴线；直线状态机每两点清空；工程用例主要验证图元与Bus提交，缺少连续真实操作/可发现性门槛。

## 改动

- 主窗口内嵌工作区与可滚动绘图/修改按钮面板，新建drawing2d直接进入；保留原有Bus一次提交与失败草稿恢复。
- UCS原点/箭头/轴名和工作平面、原点读数；离屏角标。XZ沿用既有V=-Z约定。
- 产品入口默认连续直线，Enter/Esc结束，C/按钮/首点捕捉闭合，多段线首点闭合；段级撤销及精确首点。
- 文档保存/切换/关闭保护未提交草稿；主撤销重做路由至草稿；Esc不丢整张草稿。

## 增量证据

首轮新增8测试：RED 8失败 → GREEN 8通过。保护/撤销测试先复现2失败13通过。组合回归91项中90通过，圆弧延伸hover一项受布局事件影响，已固定提示区高度，后续复跑中。针对性19项通过，严格类型0错误。完整最终数值待本轮完成记录。

渲染截图：`phase2-g-drafting-remediation/workbench-1024.png`、`workbench-1400.png`。首轮发现按钮裁切与UCS背景遮挡几何，已调整后重新渲染检查。没有替换/关闭用户正在验收的旧GUI。

## 独立审查与后续处置

一位独立审查代理只读检查本轮范围，发现2项Important、0项Critical：

1. 完成草图→再次绘图时看不到已有几何：已改为drawing2d提交后立即续开同一主工作区，保留平面/原点/缩放/平移；同基向量且共面的历史草图投影为只读背景，参与捕捉但不复制进新命令。背景不是当前草稿的可编辑对象。
2. 闭合→撤销→继续丢失连续线端点：历史恢复明确还原连线点状态，补续画与重做检查。

两项先复现RED 2失败，再修复；专项20项通过。进一步加上只读背景投影/不可选中、文档撤销重做背景刷新与提交调度拒绝恢复，专项23项通过。修复提交调度拒绝也恢复原编辑器，避免仅报忙碌却丢失入口。二维适应窗口复用主工具栏入口，新增大范围几何fit回归。

## 当前范围边界

UCS提供当前规范工作平面与原点的正确显示/输入映射，不宣称任意旋转或命名UCS管理。续画参照目前要求与当前平面共面且具有相同基向量；不同平面不伪装成可捕捉二维几何。完整已提交草图自由编辑仍不在用户选定范围。用户现有GUI进程未被关闭，旧进程不会热加载改动。

## 连续测试暴露的预选问题

草图范围80项中79通过、圆弧延伸预选1失败；不是几何求交失败。最小Qt探针证实相邻两个不同尺寸窗口将端点映射到相同全局像素(680,341)，Qt不发MouseMove，而切换工具清空了预选。固定提示区高度没有解决此根因（固定高度保留用于减少布局抖动）。新增静止指针切工具回归先失败，产品改为切换修剪/延伸/分割时从当前指针立即更新目标和预览。后续绿色组合结果在最终记录补齐。

## 最终验证（本轮最新结果）

- 新增二维专项25项，连同原草图交互共81项通过：
  `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_drafting_workbench.py tests/ui/test_sketch_editor.py -q`
  日志 `/tmp/mycad-drafting-hover-green.log`，81 passed in 44.41s。
- UI全范围+分层一次组合检查：396通过、2失败（400.34s）。失败为上述圆弧预选及 `test_symmetric_bracket_from_gui_copy_mirror_union_and_two_edges[fillet]`。没有把这次运行记为全绿。
- 三维失败追踪到直接调用 `GLViewport.refresh()` 绕过了已有定时刷新busy门控；圆角完成路径 `QTimer.singleShot(0, viewport.refresh)` 可在另一个操作进行时读取中间内核状态。新增 `test_direct_refresh_defers_kernel_read_while_execution_is_busy` 先RED（busy时重建计数2→3），再统一在refresh入口推迟读取至worker空闲。
- 修复后的视口/工作流/执行隔离/分层组合：
  `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_viewport.py tests/ui/test_p2_37_workflows.py tests/ui/test_execution.py tests/test_layering.py -q`
  58 passed in 49.89s，日志 `/tmp/mycad-drafting-refresh-green.log`。两项已知失败均有修复后绿色定向证据；按增量纪律不再重复整套UI。
- 本轮5个Python路径Ruff检查、格式检查通过；basedpyright为0 errors, 0 warnings, 0 notes。范围：`ui/sketch_editor.py`、`ui/main_window.py`、`ui/viewport.py`、`tests/ui/test_drafting_workbench.py`、`tests/ui/test_viewport.py`。
- 原生XCB隔离显示渲染1400×900及1024×768，检查常驻绘图/修改按钮、UCS、提交轮廓+续画圆、活动按钮、坐标输入、滚动参数与确认入口；截图已更新为最后一轮。未操作用户当前窗口，也未替代用户人工验收。

## 用户复验入口

先保留旧进程中的需要内容，再重启MyCAD。`文件 → 新建二维图` 直接进入主工作区。

1. 连续点击三个以上点，应逐段接线；Enter或Esc结束保留线段。
2. 再画一条链，C或“闭合”按钮闭合；撤销后从原末点继续。靠近首点出现“闭合首点”，点击也闭合。
3. 检查UCS轴名、箭头、原点与平面，平移原点屏外后方向提示仍可见。
4. 检查绘图/修改分组按钮；选择元素后设置修改参数并执行。
5. 完成草图后继续画圆，已提交轮廓仍可见并可捕捉；保存/撤销/重做核对无重复图元。

此轮未创建提交、推送或改写存档协议。独立审查2项Important均修复；未遗留本轮已知失败。任意旋转/命名UCS、已提交草图自由编辑不在本轮声明内。
