# 二维文字与字体：单元测试入口记录

日期：2026-11-17。基线：8b5c113；工作分支 codex/phase2-foundation。

## 实现范围及证据

| 要求 | 当前实现 | 对应开发检查 |
|---|---|---|
| 独立 TEXT / MTEXT、结构化 STYLE | core/drawing_text.py，五条 drawing.text / text_styles 命令；仅独立二维草图 | tests/core/test_drawing_text.py；tests/app/test_drawing_text.py |
| Bus 唯一写入、原子失败、撤销/重做、保存重开 | kernel 文本状态参与 reset/adopt/replay/regenerate；不进入约束及轮廓求解；存档最低 v4，无新顶层字段 | 生命周期、失败回滚、文档门控、自定义图层再生检查 |
| 系统字体与应用字体导入 | FontManager 枚举、TTF/OTF/TTC 用户库、哈希去重、重启加载、无效字体清理；系统设置可独立打开字体管理 | test_font_manager.py 3 项；test_font_resources.py 3 项；已有系统设置保存/取消 2 项 |
| 字体替代与中文绘制 | 保留请求字体、实际字形检测、缺字/替代信息；Qt shaping，以 cap-height 定义毫米字高 | 字体资源/布局检查；canvas-preview.png 目视检查 |
| 样式管理 | 新建、重命名、设为当前、使用中删除保护、取消隔离；切换字体清除旧文件标识；按实际字体族列字形 | test_text_style_dialog.py 4 项 |
| 排版与画布一致 | 同一布局绘制和拾取；字高、宽度因子、旋转、对齐、框宽、换行、行距；斜体外伸包含于边界 | test_text_layout.py；MTEXT 行距按 DXF 5/3 cap-height 规则定向检查 |
| 交互和属性 | CLI TEXT/MTEXT/STYLE、工具栏/菜单、覆盖式原生编辑器、Ctrl+Enter/Esc、双击编辑、点选/框选、图层与属性面板 | test_drawing_text_tools.py；未提交文字阻止保存/完成草图/文档撤销；多选只应用本次编辑字段 |
| 变换和撤销 | 文字及与普通草稿/已保存几何混合移动、复制、旋转、缩放、镜像、删除；共同提交/整体撤销 | 混合已保存对象和草稿变换/撤销；退化变换不抛出 Qt 异常 |
| 跨文档混合剪贴板 | 携带文字、几何、图片和用到的样式；稳定 ID、大小写重名、目标图层及尺寸样式协调；一次撤销 | test_text_clipboard.py；test_drawing_text_import.py 的纯文字及带/不带几何混合图片检查 |
| DXF 交换 | 原生 TEXT/MTEXT/STYLE，纯文字，无需空草图；原生内容/位置优先；Unicode 和格式码转义；单位转换 | test_dxf_text_exchange.py 18 场景；直接关联既有 DXF provider 检查 |
| 架构及检查 | core 无 Qt/后端/numpy；无类型抑制；README 同步 | tests/test_layering.py 6 项通过；31 个改动 Python 文件 lint/格式通过；各改动路径 strict typing 分组通过 |

## 审阅修复

独立审阅指出并修复：字体变更残留旧文件标识、大小写样式冲突、粘贴前置状态检查、编辑初始预览/缓存、编辑中误应用属性、多对象属性误覆盖、混合草稿撤销路由、未提交文字生命周期保护、退化/过期变换、混合剪贴板尺寸样式协调、MTEXT 原生字宽/字高默认值和行距语义。两个最终 Important 发现经原审阅者定向复核确认已解决。

## 直接关联的已有回归

- 内置命令目录/顺序/代理计划排除表 3 项，以及 CLI 目录/插件输出 3 项通过；同时补齐原基线已有但断言遗漏的 dimension_styles.set、clipboard.prepare。
- 普通几何菜单复制粘贴、普通文字控件快捷键、COPYCLIP/PASTECLIP 3 项通过。
- 独立二维文档新建/保存/重开及原有草稿缩放撤销 2 项通过。
- 分层检查 6 项通过。

所有检查按子项运行，已通过且未受后续变更影响的项未重复。未执行项目全量测试或跨平台验收。

## 正式单元测试入口

后续按缺口选择子项，避免无差别重跑上述已确认项。新增测试已成功收集为 **64 个场景**（仅收集检查，不代表一次执行了全部场景）。文件分别为：

- tests/core/test_drawing_text.py
- tests/app/test_drawing_text.py
- tests/app/test_drawing_text_import.py
- tests/formats/test_dxf_text_exchange.py
- tests/ui/test_font_manager.py
- tests/ui/test_font_resources.py
- tests/ui/test_text_layout.py
- tests/ui/test_text_style_dialog.py
- tests/ui/test_drawing_text_tools.py
- tests/ui/test_text_clipboard.py

调用模板：`QT_QPA_PLATFORM=offscreen uv run --no-sync pytest <上述单个文件>::<待验证场景> -q`。
正式阶段优先补充本机真实中文输入法组合输入、Windows 原生字体目录/界面、不同 DPI、外部 CAD 实机 DXF 显示，以及大文本/多文档交互等尚未现场验收场景。

## 已明确边界

首批 MTEXT 为统一样式，不包含局部富文本、分栏和 SHX 字形绘制；这些 DXF 内容明确报告近似或不支持。DXF 不嵌入字体。MTEXT 基线对齐转换为原生底部锚点时报告提示，AtLeast 行距导入提示转换为固定行距。含暂存相切/关联阵列的复杂草稿须先完成，再执行文字与几何混合变换，避免向原有几何暂存时间线写入不受支持的注释状态。
