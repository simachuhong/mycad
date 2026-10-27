# 二维旋转、镜像、多边形与点阵网格修补

日期：2026-10-26。用户确认按建议直接修补，范围为二维绘图/草图交互，以及二维和三维 XY 工作网格显示。

## 交付行为

- 旋转：支持先选对象或先启动命令，拾取中心后鼠标指定角度，或直接键入角度、Enter 确认。可选中心—起始参考点—目标方向三点参考旋转。保留数值中心/角度按钮；拾取中心后使用该中心。
- 镜像：两点定义任意方向的无限长轴，默认保留原对象，可取消勾选以替换。选项在命令启动后修改也会同步到预览和提交。
- 两种变换均保留预览、Esc 取消、撤销/重做、锁定/隐藏图层和用户约束保护。不改变已提交对象的既有只读参照规则。
- 正多边形：3–128 边，内接圆和外切圆，中心后指定顶点或边中点。使用既有闭合多段线表示，无新存档实体类型；已验证保存重放及 DXF 往返。
- 二维网格：用交点点阵替代线格，复选框及 F7 显隐。隐藏不改变栅格捕捉；延续绘图工作区时保留设置。F7 支持参数框和悬浮工具栏焦点。
- 三维 XY 网格：使用 GLScatterPlotItem 点阵，保留既有视图菜单显隐入口。

## 验证记录

- 修改前相关测试：61 passed。
- 全量测试：1887 passed in 608.69s；测试收集发生在最后两项选项同步修补之前，最终代码的相关 83 项已另行全部通过。
- 核心交互新增用例先失败后通过；独立审查发现的数值旋转中心回退、悬浮工具栏 F7 两项问题均完成红绿回归。
- 最终局部代码：83 passed（旋转/镜像、多边形/网格、原移动复制和原草图编辑测试）。
- 全量 lint：通过；全量格式：347 files already formatted；全量类型：0 errors, 0 warnings, 0 notes。
- 最后局部选项同步修改后，再次通过 scoped lint、format、basedpyright 和上述 83 项测试。
- 独立审查已复核数值入口、F7 和最后的选项同步修改，无剩余具体发现。
- Xvfb/XCB 原生 OpenGL 渲染：context valid=True，700×600 framebuffer，已目视确认点阵无连接线。

## 界面证据

- [正多边形和点阵](drafting-interaction-repairs/polygons-dot-grid.png)
- [隐藏网格](drafting-interaction-repairs/grid-hidden.png)
- [任意轴镜像预览](drafting-interaction-repairs/mirror-preview.png)
- [OpenGL XY 点阵](drafting-interaction-repairs/xy-dot-grid.png)

## 参考

- [AutoCAD ROTATE](https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-Core/files/GUID-1C265537-FBAC-48D5-B448-B72E777071E5.htm)
- [AutoCAD 二维镜像](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-75AADC72-8BFA-4F42-BFD1-1852F3EE61DC.htm)
- [Solid Edge Sketching 官方教程](https://support.industrysoftware.automation.siemens.com/training/se/en/ST4/pdf/spse01510-s-1040_en.pdf)

现有工作区已有大量未提交内容；本任务采用增量修改，未创建提交或推送。
