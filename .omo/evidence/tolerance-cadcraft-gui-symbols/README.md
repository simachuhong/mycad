# CADCraft 图形界面公差样图检查

从 `.omo/evidence/tolerance-expert-review-2026-11-18/review-sample.my2d` 用当前 MyCAD 导出 `symbols.dxf`，包含 14 种单行符号、一个双行框及 A/B/C 三个基准。样图仅供结构和显示核对，不构成 GB/ISO 标准示范。

在隔离 Xvfb 会话启动 CADCraft 0.20.1 图形程序，打开该文件，使用其自带 MCP 控制接口执行 `zoom {"mode":"extents"}` 并截取 `cadcraft-gui.png`。检查可见 14 个单行框、一个双行框、直径与 M/L 标记、A/B/C 基准和对应数字；与 `mycad-preview.png` 在符号和内容上可对应，字形、间距和线宽存在软件差异。截图不能证明制图规则正确，也不代表所有字体、显示比例或 AutoCAD 外观。

使用 `ui_click` 选中左上角直线度框后，在 CADCraft 命令行输入 `DDEDIT` 并点击该框；程序提示 `Select a text, mtext, multileader, attribute definition or dimension.`，没有进入公差框编辑。此操作的反馈不证明该软件没有其他编辑路径，但不能把此路径判为可编辑。`selected-frame.png` 和 `textedit-rejected.png` 为界面记录；对应控件和步骤由 CADCraft 本地控制接口触发。

MyCAD 再次导入导出文件，对照原文档核对 15 个公差框行数据、3 个基准名称，报告无警告。该自往返仅验证本软件数据一致性；目标 CAD 的保存与可编辑性仍需另行测试。软件进程和 Xvfb 已结束。

- `symbols.dxf` SHA-256 `c1bf931e9caa5651eef534a257aebbe144638740ccfc549b2e770018a9c651f9`
- `cadcraft-gui.png` SHA-256 `1f9de770a828267e92a425f45ab76641fc44c14bfd5019a4b347af5c238419c7`
- `mycad-preview.png` SHA-256 `157a73dae81411c5906210695b6e3749a713afeb255f31d86e588a5227c0db16`
- `textedit-rejected.png` SHA-256 `65a2d7a09d90d2345e70eac2fe68386cd25564af3e5f1c9c3d08447bbcc616b9`

交接样图更新：原交接 DXF 含修复前深色真彩色，已备份为 `pre-fix-review-sample.dxf`（SHA-256 `e68df2be480b68f0184a523e4faf69b51d75e821cddc88a8d3b8af1fbbeaef87`），旧预览及清单同时保留。当前交接 DXF 和预览由不变的原生样图重新导出，散列已更新；历史 CADCraft 移动样本的来源引用已指向旧备份。
