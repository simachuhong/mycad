# 形位公差 AutoCAD 对标整改方案

状态：用户已要求依本方案开发；整包验收尚未完成。

## 对标与边界

以 AutoCAD 2026 的 TOLERANCE 对标普通公差框，以 AutoCAD Mechanical 的 AMDATUMID、AMFCFRAME 对标基准与带引线的机械标注；具体版本及参考样图须在人工验收时固定。GB/ISO 优先，符号和规则由项目专业人员复核；不声称完成标准合规判定。

保留结构化对象、Command Bus、历史重放和已有文件；统一重做交互与标注排版。图标自绘，按含义与交互对标，不复制厂商资产。

## 整改清单

1. P0：工具栏提供公差框、基准的矢量图标和合理分组，菜单与工具栏动作一致；维护功能移至非主要入口。
2. P0：以图纸单位统一基准字框、文字、三角和引线样式；支持直接、折线和无引线，正交约束及真实比例，拾取容差独立。
3. P0：基准以选择几何、指定附着位置及引线路径、输入名称为主流程，支持实时预览、默认标识、Enter 和 Esc。
4. P0：公差框使用按实际框格排列的编辑器、符号选择和预览；保留普通 TOLERANCE 编辑后放置，同时支持机械式附着及引线。
5. P0：支持捕捉、坐标输入、正交、状态提示和命令行，鼠标与键盘共享状态；选择、框选、夹点、编辑、移动、复制、删除和撤销保持一致。
6. P0：扩展对象、持久化与 DXF 保存引线及样式；旧档按旧版规则读取，迁移不得静默改变旧图；画布、拾取、框选和导出共享几何规则。
7. P1：支持附着尺寸及公差框、表面延伸/指示；高级公差表达与模板另行细化并验收。

## 验收

固定 AutoCAD 版本、制图标准、字高及样图后，分别执行工具栏视觉、基准样式、公差框编辑、创建编辑操作、锁层/撤销、保存重开及 AutoCAD DXF 交换验收。真实桌面与专业人员复核分别记录；自动测试不能代替。开发期间每项仅运行对应定向测试及必要直接关联项。

## 参考

- [AutoCAD 2026 公差编辑器](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-2821B734-18B4-4A0E-A020-318D45DDDAE1.htm)
- [Mechanical 基准创建流程](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Mechanical/files/GUID-565118FA-2EB1-4B05-AF8D-22C646934BB5.htm)
- [Mechanical 公差框命令](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Mechanical/files/GUID-983C0E59-EFFD-41A9-8971-E075DAC5A9BD.htm)
