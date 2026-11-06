# 2026-11-03：自由旋转修复与 M2-A 对标复核

## 产品修复

根因是 pyqtgraph 默认 Euler orbit 将俯仰截断在 ±90°，且维持世界 Z 朝上。Shift+中键使用的 view-upright 平移在极点退化。新增测试先得到 7 failed / 7 passed，复现上下极点、Z 倾斜及平移问题。

自由旋转使用归一化四元数和屏幕轴，标准视图继续使用原有指定角度。显示矩阵统一提供射线、投影、相机位置及深度偏移方向，文档视图状态保存完整四元数；Shift+中键沿屏幕平面平移。

独立代码审查发现相机位置返回 QVector3D 会破坏 pyqtgraph 的数组 pixelSize 接口。追加回归先复现 ValueError，再保留原 Vector 返回类型修复。最终只读复核无剩余发现。两项正视射线旧断言与 Qt 实际矩阵的 float32 误差约 1.7e-7；改为 1e-6 容差，并保留实际渲染投影/射线一致性检查。

## 验证结果

- 定向 pytest：143 passed in 193.58s；覆盖 navigation_contract、coordinate_indicator、picking、viewport、menus_toolbar、document_session 和 layering。见 `camera-regression.log`、`camera-regression.xml`。
- 改动源文件/测试的 ruff check、ruff format --check 通过。
- 改动源文件/测试及 pyqtgraph stubs 的 basedpyright：0 errors, 0 warnings, 0 notes。stubs 按仓库既有配置排除于 ruff，仍纳入严格类型检查；没有新增忽略规则。
- Xvfb + xcb + 软件 OpenGL 原生窗口模拟中键：有效上下文与非空 framebuffer，视角跨过顶部至下方且 Z 可倾斜。复现脚本 `camera-smoke.py`，截图 `free-orbit-native-gl.png`，数值 `camera-smoke.json`。
- git diff --check 通过。

这是定向修复验证，不关闭 M0/M1 或全项目的最终全量四门。

## M2-A 文档复核

交付为 `docs/superpowers/specs/2026-11-03-m2a-datum-interaction-design.md`：16 项对标、17 项操作验收、12 条 Siemens 官方来源。历史资料版本、SDK/GUI 证据边界与大型 PDF 仅核查索引段落的限制均已标注。

增加双向选择、预高亮及重叠消歧、显隐与过滤、位姿/方向约定、锁面独立于相机、精确捕捉及离面投影、三独立开关和事务失效条件。独立设计审查指出共享定位缺少 GUI 消费者，现明确由坐标系原点定位步骤承载，并补 world→parent 转换、数值优先、采用草稿及外层 Bus 确认的验收。复审结果为 nothing important left。

本次没有实施 M2-A 产品功能；文档状态为设计复核待实施。静态检查通过：矩阵数量、来源锚点、相对引用、长行和空白。

原有未提交工作保留；无 commit、push 或全量验收声明。
