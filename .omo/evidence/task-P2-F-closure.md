# P2 F 收口记录：专业工作台与可视性

日期：2026-10-25。状态：**按用户确认范围完成工程收口，等待用户人工体验验收**。

## 范围与依据

用户明确选择“先收口 F，二维/草图随 G 联验”。因此 P2-29/P2-31 的三维工作台、平面视图基础、导航、选择和现有八条命令的预览确认在 F 收口；P2-32+ 的真实二维图元、工作平面编辑、草图约束与建模区域选择仍由 G 联验。此裁定取代 2026-10-24 因 G 依赖而整体保持 partial 的状态，不代表二维/草图已实现。

依据：`docs/design/phase2-workbench-v1/03-model.png` 的五区布局、中文任务组织、画布优先和明确预览/应用；`docs/design/solid-edge-interaction-acceptance.md` 的鼠标选择、非模态参数、连续导航、动态尺寸和显式确认契约。未运行 Solid Edge 做逐功能对照；不宣称达到 Solid Edge 全产品能力。

## 本轮实际修复

| 子项 | 修复及交付 |
|---|---|
| P2-31 导航 | 空闲与建模统一中键旋转、Shift+中键平移、滚轮缩放、中键双击适应；左拖框选；Esc 中断框选后仍按住左键不会误转视图。自由旋转清除失效的标准视图勾选，并显示自由视角与投影。 |
| P2-31 选择 | 结构树显示当前模型的真实实体；模型选择同步所属实体和属性，多实体均高亮；点实体树不误入历史预览，不重置相机距离/中心。不猜测实体与历史特征的归属关系。 |
| P2-31 预览/确认 | 现有八条建模命令沿用统一手柄、非阻塞预览及明确提交；输入定值不提交，预览可继续选面/边和导航；无效输入阻止提交旧预览；取消恢复当前模型。补充小屏命令条、原模型重选与历史不变验证。 |
| P2-29 布局 | 参数条固定在视口外；字段区域可横向滚动，应用/取消固定可见；683 logical px 宽度不再被撑到 1266。聚焦末尾尺寸字段时完整显示输入框，修复 Qt 内部行编辑器滚动仅露出一角的问题。 |
| P2-29 信息/图标 | 沿用集中 SVG 图标，覆盖工具栏、菜单、命令库及结构树。命令库按“创建特征/修改”默认展开；树与命令库显示中文名，技术 ID 保留在提示与搜索。长状态文本不再撑宽窗口。 |
| P2-28/30 显示 | 暗色主题同步 GL 背景和边线；候选几何使用蓝色，取消恢复实体色；shader 编译对象归各视口/GL 上下文所有，修复多个窗口共用缓存造成 key_light uniform/程序无效。保留原 BREP、四模式和性能验收。 |
| 命令速查 | 修复嵌套 oneOf/$ref 下所选面参数说明缺失；循环引用有边界保护。 |

## 验证结果

- 最终完整 UI 加关联协议、几何、架构和命令语法范围：**297 passed in 211.46s**。
- 测试代码类型整理后，执行/历史编辑/打开原子性/测量/右栏五组再跑：**27 passed in 24.69s**。这些是重复验证，不累加成独立测试数。
- 复核发现的相机跳动、Esc 后误转和多实体树高亮问题，补充定向回归：**9 passed**；修复前有失败证据。
- Ruff 检查通过、44 个文件格式检查通过；basedpyright **0 errors, 0 warnings, 0 notes**；`git diff --check` 通过。最后一处测试变量命名整理后打开原子性两项再跑通过。
- 静态检查、截图报告及最终日志见本目录下 `phase2-foundation/p2-f-closure/`。本次未跑整个项目全部测试，不把此范围称为全仓全绿。

复现主回归：

```bash
QT_QPA_PLATFORM=xcb uv run pytest tests/ui tests/core/test_viewport_protocol.py tests/geom/test_viewport_snapshots.py tests/geom/test_face_extrude.py tests/test_layering.py tests/commands/test_grammar.py -q
uv run ruff check src/mycad/ui src/mycad/commands/grammar.py tests/ui
uv run ruff format --check src/mycad/ui src/mycad/commands/grammar.py tests/ui
uv run basedpyright src/mycad/ui src/mycad/commands/grammar.py tests/ui
```

## 显示与高 DPI 证据

[8 组合报告](phase2-foundation/p2-f-closure/matrix.json)：1920×1080、1366×768 × Qt DPR 1/1.25/1.5/2，使用隔离 Xvfb/xcb + Mesa llvmpipe GL，实际检查 Qt DPR；不是八台物理显示器。每组记录八条命令的确认按钮、末尾参数焦点可见性、0.5/1/2 相机缩放的 5.9px 命中/6.1px 不命中、拉伸预览中旋转后重选面、Enter 不提交、取消不改历史，以及四状态截图的 GL framebuffer 像素一致性。

另在当前 **DISPLAY=:1 / Intel HD Graphics 620 / Mesa 25.2.8** 上复跑：
[原生桌面报告](phase2-foundation/p2-f-closure/native-intel-1920x1080-1/report.json)。目标屏幕 1920×1080，窗口管理器保留桌面区域后实际客户区 **1920×1015**；常规视口占 **67.79%**，隔离精确 1920×1080 客户区为 **68.21%**。不将受桌面限制的客户区误记为 1080 高。

- [原生桌面拉伸预览](phase2-foundation/p2-f-closure/native-intel-1920x1080-1/extrude-preview.png)
- [1366×768 / 200% 拉伸预览](phase2-foundation/p2-f-closure/1366x768-2/extrude-preview.png)
- [1366×768 / 200% 阵列末尾输入](phase2-foundation/p2-f-closure/1366x768-2/pattern-parameters.png)
- [1366×768 / 200% 暗色当前模型](phase2-foundation/p2-f-closure/1366x768-2/dark-current-model.png)

矩阵验证使用长方体，圆角/孔洞/薄板/圆柱等渲染案例沿用 P2-28/30 的已确认实机证据。小屏高缩放时命令库按需收起，主工具栏动作使用原生溢出/菜单，参数条可横向滚动；不承诺所有字段同时显示。

## 用户人工走查（待用户执行）

1. 当前法兰上选上表面→拉伸，完整面含孔洞参与；拖箭头/输入正负距离；预览中用中键旋转再选面。Enter 只定值，右键/应用才提交；取消及撤销恢复正确。
2. 圆角命令连续增删所选边、输入半径；预览中旋转选另一条边。失败时可减小半径，不能提交上一次有效结果。
3. 孔在所选平面点击重新定位；圆柱/长方体/差集切换尺寸字段调整手柄；旋转/孔阵列调整角度。复杂几何可行性以实际内核结果为准。
4. 空闲与命令中检查中键、Shift+中键、滚轮一致；框选按 Esc 后保持左键移动，不应旋转或提交。
5. 点击实体树、模型面及多选实体，检查所属实体和属性一致；选择不会改变当前缩放。点击历史特征则进入历史预览，并可返回当前模型。
6. 收窄窗口/提高缩放，Tab 到参数条末尾输入，确认整个数字字段以及应用/取消可用；切换明暗主题，模型、孔壁、边线、选择和候选预览均可辨。

## 仍由后续验收的边界

G：真实二维绘图、任意草图区域、工作平面/约束/捕捉及其联动；完整同步面编辑、密集几何 QuickPick、任意旋转轴和通用种子/刀具体拾取也未在本轮补齐。当前三维命令的几何限制仍以操作验收基线为准。本记录是 F 工程收口，不替代用户人工体验确认，也不是 Phase 2 发布验收。

## 人工验收启动

已启动 `MyCAD — P2 F 收口验收版`，载入仓库 `flange.mc.json`（3 条命令），保留其他已有应用窗口。此窗口沿用用户保存的布局，可能显示较宽右栏和已展开 CLI；上述 67.79% 是基线布局测量值，不是此旧布局启动值。可通过“视图 → 重置工作台布局”恢复原型布局。启动回执与 [实际启动截图](phase2-foundation/p2-f-closure/manual-review-startup.png) 已保存；用户尚未给出人工验收结论。
