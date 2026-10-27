# Solid Edge 鼠标操作研究

研究日期：2026-10-25。状态：官方资料与 MyCAD 源码对照，尚未进行 Solid Edge 实机复现；本文不是已批准的实现规格。

用户要求先学习 Solid Edge 的鼠标操作经验，暂停沿现有大表单交互继续开发。研究重点是每个动作的前置状态、反馈、完成条件，以及操作过程中模型是否始终可见。

## 视图导航

以下来自 Siemens 2019 年的鼠标滚轮操作文章，适用文中所述三维环境。不同环境和用户设置可能改变行为。

| 鼠标动作 | 文档行为 |
|---|---|
| 滚动滚轮 | 缩放；方向可以设置反转 |
| 按住中键移动 | 旋转视图 |
| Shift 加中键拖动 | 平移视图 |
| Ctrl 加中键拖动 | 连续缩放 |
| Alt 加中键拖动 | 区域缩放 |
| 双击中键 | 适应窗口 |

该文还说明可以指定旋转点或轴，并在后续建模操作间保留。视图围绕哪里旋转，也是操作习惯的一部分。

来源：[25 Uses of the Scroll Wheel in Solid Edge](https://blogs.sw.siemens.com/solidedge/25-uses-of-the-scroll-wheel-in-solid-edge/)，2019-04-25。

## 选择与重叠对象

草图教材中的基础过程是先悬停高亮，再单击选取；Ctrl 或 Shift 配合单击可以多选或取消选中项。拖动围栏可批量选取。这些草图规则不能未经核对就推广到所有三维命令。

来源：[Solid Edge ST5 Fundamentals，Editing and modifying sketches](https://support.industrysoftware.automation.siemens.com/training/se/en/ST5/pdf/mt01413-s-1050_en.pdf)，教材页 1-34。

Draft 环境的官方文章区分两种框选：从左向右要求完整包含，从右向左允许相交。QuickPick 则处理同一鼠标位置的多个候选：悬停后出现提示，调用候选列表，指向列表项时对应对象高亮。触发等待时间与调用鼠标键存在设置项。

来源：[Select and you are all Set](https://blogs.sw.siemens.com/solidedge/Select-and-you-are-all-Set/)，2014-05-16，明确讨论 Draft 环境。

对 MyCAD 的启示：一次没有选到预期对象，应提供辨认候选与纠正选择的路径；不能只靠反复放大、缩小或重试同一个像素。

## 右键需要结合操作状态理解

| 情境与动作 | 官方文章描述 |
|---|---|
| 命令栏存在 Accept 或 Finish，图形区空白处右键 | 接受当前步骤或完成 |
| 按住右键 | 显示径向菜单 |
| 右键方向手势 | 可直接调用对应扇区命令 |
| 重叠对象处停留后右键 | 调用 QuickPick |
| Shift 加右键拖动 | 旋转视图 |
| Ctrl 加 Shift 加右键拖动 | 平移视图 |
| Ctrl 加右键拖动 | 连续缩放 |

来源：[Right-Click Commands in Solid Edge Part 1](https://blogs.sw.siemens.com/solidedge/Right-Click-Commands-in-Solid-Edge-Part-1-User-Interface/)，2019-06-29。该文不是各状态冲突优先级的完整规范。

Solid Edge 2025 增加了上下文工具条是否由右键调用、闲置时是否淡出的设置；垂直命令栏还可自动隐藏。新版工具条不能与早期资料中的径向菜单、QuickPick 混为一个控件。

来源：[New in Solid Edge 2025 UI/UX workflow enhancements](https://blogs.sw.siemens.com/solidedge/new-in-solid-edge-2025-ui-ux/)，2024-11-11。

对 MyCAD 的启示：必须先区分按下、松开、持续时间、移动距离、修饰键、命中对象和命令步骤，再决定动作。短按、长按、拖动不应在同一次操作中重复触发；等待阈值及冲突优先级仍需实机记录。

## 直接操纵几何与尺寸输入

ST5 同步建模教程展示：选面出现操纵柄，点击轴指定移动方向，随后移动鼠标、捕捉关键点或输入距离确定位置。点击圆环进入几何旋转，可输入角度。教材中存在“点击进入，再移动，再点击确定”的过程，不能把所有操作笼统实现成“必须一直按住左键拖动”。移动操纵柄与移动几何也需要区分。

来源：[Moving and rotating faces，ST5](https://support.industrysoftware.automation.siemens.com/training/se/en/ST5/pdf/spse01520-s-1050_en.pdf)，教材页 3-7、3-10、3-20。具体按钮释放时机、Esc 各层级退出效果仍需实机确认。

ST3 圆角教材给出的顺序是启动命令、选择对象类型、选边后动态预览、输入半径、继续选同半径的边，右键完成该组后命令仍保持活动。

来源：[Constructing treatment features，ST3](https://support.industrysoftware.automation.siemens.com/training/se/en/ST3/pdf/spse01530.pdf)，教材页 3-3。

ST3 同步拉伸支持先选草图区域，再点拉伸手柄，通过鼠标确定范围或在动态输入框键入数值。该教程支持点击或输入数值后按 Enter 完成相应步骤。

来源：[Constructing base features，ST3](https://support.industrysoftware.automation.siemens.com/training/se/en/ST3/pdf/spse01515.pdf)，教材页 3-8。同步操作手感可借鉴，但不能据此宣称 MyCAD 已具备同步建模的约束求解能力。

## MyCAD 当前代码与上述经验的冲突

以下是本次读取工作区代码所得，未修改产品代码。

| 位置 | 当前行为 | 对操作造成的影响 |
|---|---|---|
| `src/mycad/ui/viewport.py` 的 `mouseMoveEvent` 及安装的 pyqtgraph `GLViewWidget.mouseMoveEvent` | 大部分导航转交绘图库；默认左键拖动旋转，中键拖动平移 | 鼠标职责与参考习惯不一致；轻微拖动可能改变视角 |
| `viewport.py` 的 `mousePressEvent` | 活动建模命令中，右键按下立即发出面板定位事件 | 尚未判断是短按、长按还是拖动就触发动作 |
| `main_window.py` 的 `_on_viewport_context_requested` | 将右键用于移动参数面板 | 用户必须额外管理面板的位置 |
| `viewport.py` 的 `selection_target_at` | 存在候选预览时直接返回空 | 预览期间不能继续按原模型拓扑选边 |
| `viewport.py` 的 `show_candidate_preview` | 清除选择，并使用 `fit_camera=True` 渲染 | 预览会打断选取反馈，并可能改变正在观察的位置 |
| `plan_cards.py` 的 `_ParamDialog` | 300 至 420 像素宽的表单，预览需要另点按钮 | 占用模型区域，选取和结果观察之间反复切换 |

对这些问题的研究结论：后续设计应共同处理鼠标输入、命令步骤、选择集、相机和临时几何的关系。只调整弹窗大小，无法解决连续操作中断。

## 实机学习清单

以下尚未执行。每个场景应记录 Solid Edge 版本、同步或顺序环境、鼠标设置、按键按下与释放、指针轨迹，以及每一步的画面。

| 场景 | 要观察的细节 |
|---|---|
| 空闲视图导航 | 中键旋转中心、缩放中心、Shift 平移、双击适应；是否受指针位置影响 |
| 密集边和遮挡面选择 | 预高亮顺序、QuickPick 触发条件、列表高亮、退出后选择是否保留 |
| 连续圆角 | 先选边与先启动命令两条路径；追加、移除边；修改半径；右键完成一组后的状态 |
| 圆角过程中导航 | 预览和选择是否保持；旋转结束后能否继续加边；是否发生相机重置 |
| 无效圆角半径 | 是否保留选择与原模型；恢复有效半径需要哪些动作；失败提示在哪里 |
| 拉伸与操纵柄 | 点击后移动和按住拖动各自是否支持；输入焦点、方向切换、确认时机 |
| 孔的鼠标放置 | 面锁定、孔中心跟随、捕捉、定位尺寸、连续放孔及结束方式 |
| 右键冲突 | QuickPick、步骤确认、上下文工具条、径向菜单同处可用状态时谁优先 |
| 逐步取消 | Esc 在输入、拖动、选取、命令完成后分别如何处理；不会误撤销已完成操作 |
| 窄视口与高分辨率 | 工具条遮挡、闲置隐藏、数值框位置、点击目标尺寸与焦点保持 |

记录应能回答“为什么下一次鼠标动作自然且可预测”。在这些流程的行为尚未明确前，不将旧的参数面板方案作为后续开发基线。
